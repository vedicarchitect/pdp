"""Walk-forward (out-of-sample) optimizer for the directional-strangle strategy.

This is the Phase-4 go/no-go gate. Full-sample optimization curve-fits; instead we roll a
fixed in-sample (IS) window forward and only ever *select* parameters on IS, then score the
*next* out-of-sample (OOS) window the strategy has never seen. Stitching every fold's OOS
slice end-to-end yields an honest equity curve: if that is robustly profitable the edge is
real, otherwise it was overfitting.

Efficiency: ``build_strangle_day`` assembles raw multi-timeframe inputs (EMAs, Camarilla,
VWAP, ORB, VIX) that do **not** depend on the parameters being optimized — the bias weights,
thresholds, ratio table, exits, and hedge flag are all applied later in ``score_bias`` /
``simulate_strangle_day``. So each day's data is built once per fold and every candidate config
is just a cheap re-simulation over it.

To keep the search honest the free parameters are *grouped* into a handful of knobs (weight
profile, aggressiveness→thresholds, take-profit, hedge on/off) rather than ~12 independent dials.

Usage:
  python backtest/strangle_walkforward.py --from 2021-06-01 --to 2026-05-31
  python backtest/strangle_walkforward.py --from 2022-01-01 --to 2024-12-31 \
      --is-months 12 --oos-months 3 --step-months 3 --objective sharpe --out logs/wf.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient  # noqa: E402

# Reuse the runner's VIX loader so the gate sees identical data.
from strangle_run import load_vix_window  # noqa: E402

from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator  # noqa: E402
from pdp.backtest.day_loader import load_window  # noqa: E402
from pdp.backtest.strangle_config import StrangleConfig  # noqa: E402
from pdp.backtest.strangle_loader import build_strangle_day  # noqa: E402
from pdp.backtest.strangle_sim import StrangleDayData, simulate_strangle_day  # noqa: E402
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar  # noqa: E402
from pdp.settings import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("wf")

_TRADING_DAYS_PER_YEAR = 252
_MIN_OOS_DAYS = 8        # a fold's OOS slice needs at least this many traded days to count
_MIN_IS_TRADES = 20      # reject IS candidates that barely traded (not a real fit)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


@dataclass
class Metrics:
    days: int
    trades: int
    net: float
    pf: float
    win: float
    max_dd: float
    sharpe: float
    calmar: float


def compute_metrics(results: list) -> Metrics:
    """Headline metrics over a list of per-day ``DayResult`` (None entries ignored)."""
    traded = [r for r in results if r is not None]
    rets = [r.realized for r in traded]
    n = len(rets)
    gp = sum(x for x in rets if x >= 0)
    gl = sum(x for x in rets if x < 0)
    wins = sum(1 for x in rets if x >= 0)
    eq = peak = max_dd = 0.0
    for x in rets:
        eq += x
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    net = gp + gl
    mean = (net / n) if n else 0.0
    if n > 1:
        var = sum((x - mean) ** 2 for x in rets) / (n - 1)
        std = math.sqrt(var)
    else:
        std = 0.0
    sharpe = (mean / std * math.sqrt(_TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    return Metrics(
        days=n,
        trades=sum(len(r.trades) for r in traded),
        net=net,
        pf=(gp / abs(gl)) if gl else (float("inf") if gp > 0 else 0.0),
        win=(wins / n * 100) if n else 0.0,
        max_dd=max_dd,
        sharpe=sharpe,
        calmar=(net / max_dd) if max_dd > 0 else (float("inf") if net > 0 else 0.0),
    )


def objective(m: Metrics, kind: str) -> float:
    """Scalar IS score; rejects under-traded fits so a single lucky day cannot win."""
    if m.trades < _MIN_IS_TRADES or m.days < _MIN_OOS_DAYS:
        return float("-inf")
    if kind == "sharpe":
        return m.sharpe
    if kind == "calmar":
        return m.calmar if m.calmar != float("inf") else 1e9
    if kind == "pf":
        return m.pf if m.pf != float("inf") else 1e9
    if kind == "net":
        return m.net
    raise ValueError(f"unknown objective: {kind}")


# --------------------------------------------------------------------------- #
# Grouped candidate space (kept small to avoid overfitting)
# --------------------------------------------------------------------------- #

# Weight profiles — which signal families lead. Only keys that exist on BiasWeights.
_WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "trend": {"w_ema_1h": 2.5, "w_ema_15m": 2.0, "w_ema_5m": 1.5,
              "w_cam_daily": 1.0, "w_cam_weekly": 1.0, "w_swing": 1.0,
              "w_vwap": 1.0, "w_orb": 1.0, "w_pcr": 1.0},
    "balanced": {"w_ema_1h": 2.0, "w_ema_15m": 1.5, "w_ema_5m": 1.0,
                 "w_cam_daily": 1.5, "w_cam_weekly": 1.5, "w_swing": 1.0,
                 "w_vwap": 1.0, "w_orb": 1.0, "w_pcr": 1.0},
    "levels": {"w_ema_1h": 1.0, "w_ema_15m": 1.0, "w_ema_5m": 0.5,
               "w_cam_daily": 2.0, "w_cam_weekly": 2.0, "w_swing": 1.5,
               "w_vwap": 1.0, "w_orb": 1.0, "w_pcr": 1.5},
}

# Aggressiveness — how strong a lean must be to size up (bucket thresholds).
_AGGRESSIVENESS: dict[str, dict[str, float]] = {
    "conservative": {"th_complete": 0.85, "th_most": 0.60, "th_more": 0.30},
    "moderate": {"th_complete": 0.75, "th_most": 0.50, "th_more": 0.20},
    "aggressive": {"th_complete": 0.60, "th_most": 0.40, "th_more": 0.15},
}

_TAKE_PROFITS = [0.4, 0.5, 0.6]
_HEDGES = [False, True]


@dataclass
class Candidate:
    label: str
    cfg: StrangleConfig


def build_candidates(base: StrangleConfig) -> list[Candidate]:
    """Cross the grouped knobs into runnable ``StrangleConfig`` variants."""
    out: list[Candidate] = []
    base_d = base.to_dict()
    for pname, pw in _WEIGHT_PROFILES.items():
        for aname, th in _AGGRESSIVENESS.items():
            for tp in _TAKE_PROFITS:
                for hedge in _HEDGES:
                    d = dict(base_d)
                    w = dict(d["weights"])
                    w.update(pw)
                    w.update(th)
                    d["weights"] = w
                    d["take_profit_pct"] = tp
                    d["hedge_enabled"] = hedge
                    out.append(Candidate(
                        label=f"{pname[:4]}/{aname[:4]}/tp{tp}/{'H' if hedge else 'N'}",
                        cfg=StrangleConfig.from_dict(d),
                    ))
    return out


# --------------------------------------------------------------------------- #
# Folds
# --------------------------------------------------------------------------- #


def _add_months(d: date, m: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + m
    return date(total // 12, total % 12 + 1, 1)


def _weekdays(start: date, end: date) -> list[date]:
    """Calendar weekdays in [start, end) — load_window/build skip the non-data ones."""
    out, d = [], start
    while d < end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@dataclass
class Fold:
    idx: int
    is_start: date
    oos_start: date
    oos_end: date


def make_folds(start: date, end: date, is_m: int, oos_m: int, step_m: int) -> list[Fold]:
    """Rolling fixed-size IS windows with a sliding OOS slice (bounded per-fold memory)."""
    folds: list[Fold] = []
    is_start = date(start.year, start.month, 1)
    i = 0
    while True:
        oos_start = _add_months(is_start, is_m)
        oos_end = _add_months(oos_start, oos_m)
        if oos_start >= end:
            break
        folds.append(Fold(idx=i, is_start=is_start, oos_start=oos_start,
                          oos_end=min(oos_end, _next_day(end))))
        is_start = _add_months(is_start, step_m)
        i += 1
    return folds


def _next_day(d: date) -> date:
    return d + timedelta(days=1)


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def run_fold(
    fold: Fold,
    base: StrangleConfig,
    candidates: list[Candidate],
    mdb,
    cal,
    commission_fn,
    vix_sid: str,
    obj_kind: str,
) -> dict | None:
    """Optimize candidates on the fold's IS slice, score the best on its OOS slice."""
    span_days = _weekdays(fold.is_start, fold.oos_end)
    window = load_window(mdb, cal, span_days)
    if not window.valid_days:
        log.warning("fold %d: no valid days in span", fold.idx)
        return None
    vix_by_day = load_vix_window(mdb, vix_sid, window.valid_days)

    # Build each day's inputs once (parameter-independent); split IS vs OOS by date.
    is_data: list[StrangleDayData] = []
    oos_data: list[StrangleDayData] = []
    for d in window.valid_days:
        data = build_strangle_day(window, base, d, vix_by_day)
        if data is None:
            continue
        (is_data if d < fold.oos_start else oos_data).append(data)
    del window  # free the raw 1m chains; the resampled day-data is all we need now

    if len(is_data) < _MIN_OOS_DAYS or len(oos_data) < _MIN_OOS_DAYS:
        log.warning("fold %d: thin data (IS=%d OOS=%d) — skipped",
                    fold.idx, len(is_data), len(oos_data))
        return None

    # In-sample selection.
    best: tuple[float, Candidate, Metrics] | None = None
    for cand in candidates:
        res = [simulate_strangle_day(cand.cfg, dd, commission_fn) for dd in is_data]
        m = compute_metrics(res)
        score = objective(m, obj_kind)
        if best is None or score > best[0]:
            best = (score, cand, m)
    assert best is not None
    _, chosen, is_m = best

    # Out-of-sample evaluation of the IS-chosen config.
    oos_res = [simulate_strangle_day(chosen.cfg, dd, commission_fn) for dd in oos_data]
    oos_m = compute_metrics(oos_res)

    log.info(
        "fold %d  IS %s..%s -> OOS %s..%s | pick=%s | "
        "IS sharpe %.2f pf %.2f net %+.0f | OOS sharpe %.2f pf %.2f net %+.0f dd %.0f",
        fold.idx, fold.is_start, fold.oos_start, fold.oos_start, fold.oos_end,
        chosen.label, is_m.sharpe, is_m.pf, is_m.net,
        oos_m.sharpe, oos_m.pf, oos_m.net, oos_m.max_dd,
    )
    return {"fold": fold, "pick": chosen, "is": is_m, "oos": oos_m, "oos_results": oos_res}


def _fmt_pf(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def print_report(rows: list[dict], obj_kind: str) -> None:
    print(f"\n{'='*108}")
    print(f"  DIRECTIONAL STRANGLE — WALK-FORWARD (objective: {obj_kind})")
    print(f"{'='*108}")
    print(f"  {'Fold':<5} {'IS window':<24} {'OOS window':<24} {'Pick':<22} "
          f"{'OOS net':>10} {'PF':>6} {'Win%':>5} {'Shrp':>6}")
    print(f"  {'-'*5} {'-'*24} {'-'*24} {'-'*22} {'-'*10} {'-'*6} {'-'*5} {'-'*6}")
    for r in rows:
        f, p, o = r["fold"], r["pick"], r["oos"]
        print(f"  {f.idx:<5} {f.is_start} .. {f.oos_start}   {f.oos_start} .. {f.oos_end}   "
              f"{p.label:<22} {o.net:>+10.0f} {_fmt_pf(o.pf):>6} {o.win:>5.0f} {o.sharpe:>6.2f}")
    # Stitched OOS equity = every fold's OOS slice end-to-end (the honest curve).
    stitched: list = []
    for r in rows:
        stitched.extend(r["oos_results"])
    agg = compute_metrics(stitched)
    print(f"  {'-'*108}")
    print(f"  STITCHED OOS:  net {agg.net:>+.0f} | PF {_fmt_pf(agg.pf)} | win {agg.win:.0f}% | "
          f"maxDD {agg.max_dd:.0f} | sharpe {agg.sharpe:.2f} | calmar {_fmt_pf(agg.calmar)} | "
          f"days {agg.days} | trades {agg.trades}")
    pos = sum(1 for r in rows if r["oos"].net > 0)
    verdict = (
        "PASS — robust OOS edge; proceed to Phase 5 paper"
        if agg.net > 0 and agg.pf > 1.2 and agg.sharpe > 0.5 and pos >= 0.6 * len(rows)
        else "REVIEW — OOS not robustly profitable; do NOT promote to paper yet"
    )
    print(f"  OOS-positive folds: {pos}/{len(rows)}   ->   {verdict}")
    print(f"{'='*108}\n")


def write_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fold", "is_start", "oos_start", "oos_end", "pick",
                    "is_net", "is_pf", "is_sharpe", "oos_net", "oos_pf", "oos_win",
                    "oos_sharpe", "oos_maxdd", "oos_days", "oos_trades"])
        for r in rows:
            f, p, i, o = r["fold"], r["pick"], r["is"], r["oos"]
            w.writerow([f.idx, f.is_start, f.oos_start, f.oos_end, p.label,
                        f"{i.net:.0f}", _fmt_pf(i.pf), f"{i.sharpe:.2f}",
                        f"{o.net:.0f}", _fmt_pf(o.pf), f"{o.win:.0f}", f"{o.sharpe:.2f}",
                        f"{o.max_dd:.0f}", o.days, o.trades])
    log.info("wrote %s", path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="date_from", required=True, help="Window start YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", required=True, help="Window end YYYY-MM-DD")
    ap.add_argument("--config-file", default=None, help="Base StrangleConfig YAML (timeframe/lot)")
    ap.add_argument("--is-months", type=int, default=12, help="In-sample window size (months)")
    ap.add_argument("--oos-months", type=int, default=3, help="Out-of-sample slice size (months)")
    ap.add_argument("--step-months", type=int, default=3, help="Roll step (months)")
    ap.add_argument("--objective", default="sharpe", choices=["sharpe", "calmar", "pf", "net"])
    ap.add_argument("--vix-sid", default=os.getenv("VIX_SECURITY_ID", "21"))
    ap.add_argument("--no-commission", action="store_true")
    ap.add_argument("--out", default=None, help="Write the per-fold report to this CSV path")
    args = ap.parse_args()

    base = StrangleConfig.from_yaml(args.config_file) if args.config_file else StrangleConfig()
    candidates = build_candidates(base)
    log.info("candidate grid: %d configs", len(candidates))

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    try:
        cal = NiftyExpiryCalendar.load(s.EXPIRY_CACHE_PATH)
    except Exception as exc:
        cal = None
        log.warning("expiry calendar unavailable (%s); using Tuesday fallback", exc)

    calc = NullCommissionCalculator(s.backtest_commission) if args.no_commission \
        else CommissionCalculator(s.backtest_commission)

    def commission_fn(side: str, turnover: float) -> float:
        return float(calc.calculate(side, Decimal(str(turnover))).total_inr)

    folds = make_folds(date.fromisoformat(args.date_from), date.fromisoformat(args.date_to),
                       args.is_months, args.oos_months, args.step_months)
    if not folds:
        print("No folds — widen --from/--to or shrink --is-months/--oos-months.")
        return 1
    log.info("%d folds (IS=%dm OOS=%dm step=%dm)",
             len(folds), args.is_months, args.oos_months, args.step_months)

    rows: list[dict] = []
    for fold in folds:
        r = run_fold(fold, base, candidates, mdb, cal, commission_fn, args.vix_sid, args.objective)
        if r is not None:
            rows.append(r)

    if not rows:
        print("No completed folds (insufficient data in the window).")
        return 1
    print_report(rows, args.objective)
    if args.out:
        write_csv(rows, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
