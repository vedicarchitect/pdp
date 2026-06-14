"""Parameter-sweep harness for the configurable SuperTrend option-selling strategy.

Loads raw 1-minute spot + option chains for the window once, then runs the config-driven engine
(``pdp.backtest.sim``) across a grid of variants and prints a ranked comparison table. No DB writes.

Usage:
  python scripts/backtest_sweep.py --days 90 --start 2026-06-12
  python scripts/backtest_sweep.py --days 60 --st "10,2;10,3" --tf "5,15" --moneyness "1,0,-1"
  python scripts/backtest_sweep.py --days 90 --config '{"st_period":10,"st_multiplier":2,"timeframe_min":15,"moneyness":0}'

Grid axes (defaults):
  --st         SuperTrend (period,multiplier) pairs, ';'-separated   [3,1;10,2;10,3]
  --tf         signal timeframes in minutes, ','-separated           [3,5,15,30,60]
  --moneyness  signed strike offsets (>0 OTM, 0 ATM, <0 ITM)         [3,2,1,0,-1,-2,-3]
  --config     run a single StrategyConfig (JSON) in detail instead of the grid
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from pymongo import MongoClient  # noqa: E402

from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator  # noqa: E402
from pdp.backtest.day_loader import biz_days, build_day_data, load_window  # noqa: E402
from pdp.backtest.sim import simulate_day  # noqa: E402
from pdp.backtest.strategy_config import StrategyConfig  # noqa: E402
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar  # noqa: E402
from pdp.settings import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("sweep")


# ── grid parsing ───────────────────────────────────────────────────────────────
def parse_st(s: str) -> list[tuple[int, float]]:
    out = []
    for pair in s.split(";"):
        p, m = pair.split(",")
        out.append((int(p.strip()), float(m.strip())))
    return out


def parse_ints(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


# ── metrics ────────────────────────────────────────────────────────────────────
def aggregate(results: list) -> dict:
    """Aggregate per-day DayResults into sweep metrics."""
    traded = [r for r in results if r is not None]
    gp = sum(r.realized for r in traded if r.realized >= 0)
    gl = sum(r.realized for r in traded if r.realized < 0)
    net = gp + gl
    pdays = sum(1 for r in traded if r.realized >= 0)
    n = len(traded)
    trades = sum(len(r.trades) for r in traded)
    stopped = sum(1 for r in traded if r.done_reason)
    # Max drawdown of the cumulative realized-equity curve (absolute INR).
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in traded:
        eq += r.realized
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    return {
        "days": n,
        "net": net,
        "gross_profit": gp,
        "gross_loss": gl,
        "profit_factor": (gp / abs(gl)) if gl else float("inf"),
        "win_rate": (pdays / n * 100) if n else 0.0,
        "max_dd": max_dd,
        "trades": trades,
        "stopped": stopped,
    }


def run_config(cfg: StrategyConfig, window, commission_fn) -> dict:
    results = [simulate_day(cfg, build_day_data(window, cfg, d), commission_fn)
               for d in window.valid_days]
    results = [r for r in results if r is not None]
    m = aggregate(results)
    m["label"] = cfg.label()
    m["cfg"] = cfg
    m["results"] = results
    return m


# ── output ─────────────────────────────────────────────────────────────────────
def print_table(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (-(r["profit_factor"] if r["profit_factor"] != float("inf") else 1e9), -r["net"]))
    print(f"\n{'='*104}")
    print(f"  SWEEP COMPARISON  ({rows[0]['days']} traded days)  —  sorted by Profit Factor, then Net")
    print(f"{'='*104}")
    print(f"  {'#':>3}  {'Config':<22}  {'Net':>12}  {'PF':>6}  {'Win%':>5}  "
          f"{'MaxDD':>11}  {'Trades':>6}  {'Stop':>4}  {'GrossP':>11}  {'GrossL':>11}")
    print(f"  {'-'*3}  {'-'*22}  {'-'*12}  {'-'*6}  {'-'*5}  {'-'*11}  {'-'*6}  {'-'*4}  {'-'*11}  {'-'*11}")
    for i, r in enumerate(rows, 1):
        pf = "inf" if r["profit_factor"] == float("inf") else f"{r['profit_factor']:.2f}"
        print(f"  {i:>3}  {r['label']:<22}  {r['net']:>+12.0f}  {pf:>6}  {r['win_rate']:>5.0f}  "
              f"{r['max_dd']:>11.0f}  {r['trades']:>6}  {r['stopped']:>4}  "
              f"{r['gross_profit']:>+11.0f}  {r['gross_loss']:>+11.0f}")
    print(f"{'='*104}\n")


def print_detail(m: dict) -> None:
    print(f"\n{'='*100}")
    print(f"  SINGLE CONFIG: {m['label']}   ({m['days']} days)")
    print(f"{'='*100}")
    print(f"  {'Date':<12}  {'NIFTY Chg':>9}  {'Trades':>6}  {'Gross':>11}  {'Comm':>8}  {'Net':>11}  Status")
    print(f"  {'-'*12}  {'-'*9}  {'-'*6}  {'-'*11}  {'-'*8}  {'-'*11}  ------")
    for r in m["results"]:
        s = "P" if r.realized >= 0 else "L"
        stp = " STOP" if r.done_reason else ""
        print(f"  {r.date:<12}  {r.nifty_chg:>+9.2f}  {len(r.trades):>6}  {r.gross_pnl:>+11.2f}  "
              f"{r.commission:>8.2f}  {r.realized:>+11.2f}  [{s}]{stp}")
    print(f"  {'-'*78}")
    print(f"  Net {m['net']:>+.0f}  |  PF {m['profit_factor']:.2f}  |  Win {m['win_rate']:.0f}%  |  "
          f"MaxDD {m['max_dd']:.0f}  |  Trades {m['trades']}  |  Stopped {m['stopped']}")
    print(f"{'='*100}\n")


# ── auto-heal (mirror backtest_multiday) ─────────────────────────────────────────
def auto_heal(mdb, cal, dhan, days, band, no_heal: bool) -> None:
    if no_heal or cal is None or dhan is None:
        return
    try:
        from pdp.options.gap_backfill import backfill_gaps
        summary = backfill_gaps(dhan=dhan, col=mdb["option_bars"], cal=cal, days=days,
                                codes=[1, 2], band=band, only_missing=True)
        if summary.get("gaps"):
            print(f"  [auto-heal] filled {summary['days_filled']}/{summary['gaps']} day(s), "
                  f"{summary['total_inserted']:,} bars")
        else:
            print(f"  [auto-heal] window complete ({len(days)} day(s), 0 fetches)")
    except Exception as exc:  # noqa: BLE001
        log.warning("auto_heal_error (%s); proceeding with existing data", exc)


def _last_biz_day(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--start", type=str, default=None, help="End date YYYY-MM-DD (default last biz day)")
    ap.add_argument("--st", type=str, default="3,1;10,2;10,3")
    ap.add_argument("--tf", type=str, default="3,5,15,30,60")
    ap.add_argument("--moneyness", type=str, default="3,2,1,0,-1,-2,-3")
    ap.add_argument("--config", type=str, default=None, help="Run a single StrategyConfig (JSON) in detail")
    ap.add_argument("--no-commission", action="store_true")
    ap.add_argument("--no-heal", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    try:
        cal = NiftyExpiryCalendar.load(s.EXPIRY_CACHE_PATH)
    except Exception as exc:  # noqa: BLE001
        cal = None
        log.warning("expiry calendar unavailable (%s); using Tuesday fallback", exc)

    calc = NullCommissionCalculator(s.backtest_commission) if args.no_commission \
        else CommissionCalculator(s.backtest_commission)

    def commission_fn(side: str, turnover: float) -> float:
        return float(calc.calculate(side, Decimal(str(turnover))).total_inr)

    end = date.fromisoformat(args.start) if args.start else _last_biz_day(date.today())
    days = biz_days(end, args.days)

    dhan = None
    if not args.no_heal and s.DHAN_CLIENT_ID and s.DHAN_ACCESS_TOKEN:
        from dhanhq import DhanContext, dhanhq
        dhan = dhanhq(DhanContext(s.DHAN_CLIENT_ID, s.DHAN_ACCESS_TOKEN))
    auto_heal(mdb, cal, dhan, days, s.WAREHOUSE_STRIKE_BAND, args.no_heal)

    log.info("loading window once: %d biz days ending %s", len(days), end)
    window = load_window(mdb, cal, days)
    log.info("window loaded: %d valid days, %d skipped (holidays/incomplete)",
             len(window.valid_days), len(window.skipped))
    if not window.valid_days:
        print("No valid trading days in window (check data).")
        return 1

    # ── single-config detail mode ──
    if args.config:
        cfg = StrategyConfig.from_dict(json.loads(args.config))
        print_detail(run_config(cfg, window, commission_fn))
        return 0

    # ── grid sweep ──
    sts = parse_st(args.st)
    tfs = parse_ints(args.tf)
    mnys = parse_ints(args.moneyness)
    combos = [(p, m, tf, mny) for (p, m) in sts for tf in tfs for mny in mnys]
    log.info("running grid: %d combos (%d ST x %d TF x %d moneyness)",
             len(combos), len(sts), len(tfs), len(mnys))

    rows = []
    for i, (period, mult, tf, mny) in enumerate(combos, 1):
        cfg = StrategyConfig(st_period=period, st_multiplier=mult, timeframe_min=tf, moneyness=mny)
        rows.append(run_config(cfg, window, commission_fn))
        if i % 10 == 0 or i == len(combos):
            log.info("  %d/%d combos done", i, len(combos))

    print_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
