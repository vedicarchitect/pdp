"""Canonical multi-day backtest runner for the configurable SuperTrend option-selling strategy.

Loads raw 1-minute spot + option chains for the window once, then runs the config-driven engine
(``pdp.backtest.sim``) for either a single named config (per-trade detail) or a grid sweep of
variants and prints a ranked comparison table.

Modes (priority order):
  --sweep-param KEY=v1,...  sweep one field across values, print comparison table
  --st / --tf / --moneyness run the full parameter grid (any one flag triggers grid mode)
  --config-file <path>      load a named YAML config, run single-config per-trade detail
  --config <json>           parse an inline JSON config, run single-config per-trade detail
  (none of the above)       load BACKTEST_DEFAULT_CONFIG, run last-7-day per-trade detail

Modifiers (combine with any mode):
  --set KEY=VALUE           override one StrategyConfig field on top of a loaded config
                            (repeatable; applied before --sweep-param variation)

Usage:
  python backtest/run.py                                                  # default config, 7 days
  python backtest/run.py --config-file backtest/configs/st10_15m_otm1.yaml --days 30
  python backtest/run.py --config-file backtest/configs/st10_15m_otm1.yaml --set day_stop=12000 --days 30
  python backtest/run.py --sweep-param day_stop=10000,12000,15000,20000 --days 30
  python backtest/run.py --config-file backtest/configs/st10_2_5m_otm1.yaml --sweep-param day_stop=10000,12000,15000,20000 --days 30
  python backtest/run.py --days 90 --st "10,2;10,3" --tf "5,15" --moneyness "1,0,-1"

Grid axis defaults (used when flag given without value or as fallback inside grid mode):
  --st         SuperTrend (period,multiplier) pairs, ';'-separated   [3,1;10,2;10,3]
  --tf         signal timeframes in minutes, ','-separated           [3,5,15,30,60]
  --moneyness  signed strike offsets (>0 OTM, 0 ATM, <0 ITM)         [3,2,1,0,-1,-2,-3]
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


# ── runtime overrides ──────────────────────────────────────────────────────────
def apply_overrides(cfg: StrategyConfig, overrides: list[str]) -> StrategyConfig:
    """Apply --set KEY=VALUE pairs on top of a loaded config (type-coerced from existing field)."""
    d = cfg.to_dict()
    for kv in overrides:
        if "=" not in kv:
            raise ValueError(f"--set must be KEY=VALUE, got: {kv!r}")
        key, raw_val = kv.split("=", 1)
        key = key.strip()
        if key not in d:
            raise ValueError(f"Unknown StrategyConfig field: {key!r}. Known: {sorted(d)}")
        existing = d[key]
        if isinstance(existing, bool):
            d[key] = raw_val.lower() in ("true", "1", "yes")
        elif isinstance(existing, int):
            d[key] = int(raw_val)
        elif isinstance(existing, float):
            d[key] = float(raw_val)
        else:
            d[key] = raw_val
    return StrategyConfig.from_dict(d)


def parse_param_sweep(s: str) -> tuple[str, list[str]]:
    """Parse --sweep-param KEY=v1,v2,... → (key, [raw_values])."""
    if "=" not in s:
        raise ValueError(f"--sweep-param must be KEY=v1,v2,..., got: {s!r}")
    key, vals_str = s.split("=", 1)
    return key.strip(), [v.strip() for v in vals_str.split(",") if v.strip()]


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


_W = 130  # wide column width for per-day trade tables


def _print_day_detail(r) -> None:
    """Print per-trade table + leg summary for one DayResult (mirrors backtest_multiday print_day)."""
    stop = f"  [DAY STOP: {r.done_reason}]" if r.done_reason else ""
    print(f"\n{'='*_W}")
    print(f"  {r.date}  |  NIFTY {r.nifty_open:.2f} -> {r.nifty_close:.2f} "
          f"({r.nifty_chg:+.2f})  |  Expiry: {r.expiry}  |  Bars: {r.nifty_bars}{stop}")
    print(f"{'='*_W}")

    if not r.trades:
        print("  (no trades)")
        return

    print(f"  {'#':>3}  {'Side':<4}  {'Type':<2} {'Strike':>7}  {'Time':>5}  "
          f"{'Qty':>5}  {'Price':>7}  {'NIFTY':>9}  "
          f"{'CumLots':>7}  {'AvgEntry':>9}  {'LegPNL':>10}  {'DayPNL':>10}  Note")
    print(f"  {'-'*3}  {'-'*4}  {'-'*2} {'-'*7}  {'-'*5}  "
          f"{'-'*5}  {'-'*7}  {'-'*9}  "
          f"{'-'*7}  {'-'*9}  {'-'*10}  {'-'*10}  ----")
    for i, t in enumerate(r.trades, 1):
        leg_s = f"{t.leg_pnl:>+10.2f}" if t.leg_pnl is not None else f"{'':>10}"
        print(f"  {i:>3}  {t.side:<4}  {t.opt_type:<2} {t.strike:>7.0f}  "
              f"{t.bar_time.strftime('%H:%M'):>5}  "
              f"{t.qty:>5}  {t.price:>7.2f}  {t.nifty:>9.2f}  "
              f"{t.cum_lots:>7}L  {t.avg_entry:>9.2f}  {leg_s}  {t.day_pnl:>+10.2f}  {t.note}")
    print(f"  {'-'*(_W-2)}")
    print(f"  Gross premium: {r.gross_pnl:>+10.2f}   "
          f"Charges: -{r.commission:.2f}   "
          f"Realized: {r.realized:>+10.2f}")

    if r.leg_records:
        wins = sum(1 for lr in r.leg_records if lr.leg_pnl >= 0)
        losses = len(r.leg_records) - wins
        total_leg_pnl = sum(lr.leg_pnl for lr in r.leg_records)
        print()
        print(f"  LEG SUMMARY")
        print(f"  {'#':>3}  {'Type':<2} {'Strike':>7}  {'Entry':>5}  {'Exit':>5}  "
              f"{'Lots':>4}  {'AvgEntry':>9}  {'Exit Rs':>8}  {'Leg P&L':>10}  Reason")
        print(f"  {'-'*3}  {'-'*2} {'-'*7}  {'-'*5}  {'-'*5}  "
              f"{'-'*4}  {'-'*9}  {'-'*8}  {'-'*10}  ------")
        for i, lr in enumerate(r.leg_records, 1):
            print(f"  {i:>3}  {lr.opt_type:<2} {lr.strike:>7.0f}  "
                  f"{lr.entry_ist.strftime('%H:%M'):>5}  "
                  f"{lr.exit_ist.strftime('%H:%M'):>5}  "
                  f"{lr.lots:>4}L  {lr.avg_entry:>9.2f}  "
                  f"{lr.exit_px:>8.2f}  {lr.leg_pnl:>+10.2f}  {lr.reason}")
        print(f"  {'-'*90}")
        print(f"  {len(r.leg_records)} leg(s)  |  Total P&L: {total_leg_pnl:>+.2f}  |  "
              f"Win: {wins}  Loss: {losses}")


def print_detail(m: dict) -> None:
    print(f"\n{'*'*_W}")
    print(f"  SINGLE CONFIG: {m['label']}   ({m['days']} days traded)")
    print(f"{'*'*_W}")

    for r in m["results"]:
        _print_day_detail(r)

    # Final summary table
    print(f"\n\n{'*'*_W}")
    print(f"  SUMMARY  ({m['days']} days)")
    print(f"{'*'*_W}")
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
    print(f"{'*'*_W}\n")


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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=None, help="Window size in trading days (default: 7 for single-config, 90 for grid)")
    ap.add_argument("--start", type=str, default=None, help="End date YYYY-MM-DD (default: last business day)")
    # Single-config sources (mutually exclusive in practice)
    ap.add_argument("--config-file", type=str, default=None, metavar="PATH", help="Load a named YAML config for single-config detail")
    ap.add_argument("--config", type=str, default=None, help="Run a single StrategyConfig (inline JSON) in detail mode")
    # Grid axes — any non-None value triggers grid mode
    ap.add_argument("--st", type=str, default=None, help="SuperTrend pairs ';'-sep, e.g. '3,1;10,2'  [grid default: 3,1;10,2;10,3]")
    ap.add_argument("--tf", type=str, default=None, help="Timeframe minutes ','-sep, e.g. '5,15'       [grid default: 3,5,15,30,60]")
    ap.add_argument("--moneyness", type=str, default=None, help="Strike offsets ','-sep, e.g. '1,0,-1'    [grid default: 3,2,1,0,-1,-2,-3]")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", dest="overrides",
                    help="Override a StrategyConfig field on top of any loaded config, e.g. --set day_stop=12000")
    ap.add_argument("--sweep-param", type=str, default=None, metavar="KEY=v1,v2,...",
                    help="Sweep one field across values, e.g. --sweep-param day_stop=10000,12000,15000,20000")
    ap.add_argument("--no-commission", action="store_true")
    ap.add_argument("--no-heal", action="store_true")
    args = ap.parse_args()

    # Determine mode
    use_grid = any([args.st is not None, args.tf is not None, args.moneyness is not None])
    use_yaml = args.config_file is not None
    use_json = args.config is not None
    use_param_sweep = args.sweep_param is not None
    overrides: list[str] = args.overrides or []

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
    # Default days: 7 for single-config modes, 90 for grid
    days_count = args.days if args.days is not None else (90 if use_grid else 7)
    days = biz_days(end, days_count)

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

    # ── param sweep (--sweep-param KEY=v1,v2,...) ──
    if use_param_sweep:
        sweep_key, sweep_vals = parse_param_sweep(args.sweep_param)
        if use_yaml:
            base_cfg = StrategyConfig.from_yaml(args.config_file)
        elif use_json:
            base_cfg = StrategyConfig.from_dict(json.loads(args.config))
        else:
            base_cfg = StrategyConfig.from_yaml(s.BACKTEST_DEFAULT_CONFIG)
        if overrides:
            base_cfg = apply_overrides(base_cfg, overrides)
        rows = []
        for raw_val in sweep_vals:
            cfg = apply_overrides(base_cfg, [f"{sweep_key}={raw_val}"])
            m = run_config(cfg, window, commission_fn)
            m["label"] = f"{cfg.label()} {sweep_key}={raw_val}"
            rows.append(m)
        log.info("param sweep: %s across %s", sweep_key, sweep_vals)
        print_table(rows)
        return 0

    # ── single-config detail: YAML file ──
    if use_yaml:
        cfg = StrategyConfig.from_yaml(args.config_file)
        if overrides:
            cfg = apply_overrides(cfg, overrides)
        print_detail(run_config(cfg, window, commission_fn))
        return 0

    # ── single-config detail: inline JSON ──
    if use_json:
        cfg = StrategyConfig.from_dict(json.loads(args.config))
        if overrides:
            cfg = apply_overrides(cfg, overrides)
        print_detail(run_config(cfg, window, commission_fn))
        return 0

    # ── single-config detail: default config from settings ──
    if not use_grid:
        cfg = StrategyConfig.from_yaml(s.BACKTEST_DEFAULT_CONFIG)
        if overrides:
            cfg = apply_overrides(cfg, overrides)
        print_detail(run_config(cfg, window, commission_fn))
        return 0

    # ── grid sweep ──
    sts = parse_st(args.st or "3,1;10,2;10,3")
    tfs = parse_ints(args.tf or "3,5,15,30,60")
    mnys = parse_ints(args.moneyness or "3,2,1,0,-1,-2,-3")
    combos = [(p, m, tf, mny) for (p, m) in sts for tf in tfs for mny in mnys]
    log.info("running grid: %d combos (%d ST x %d TF x %d moneyness)",
             len(combos), len(sts), len(tfs), len(mnys))

    rows = []
    for i, (period, mult, tf, mny) in enumerate(combos, 1):
        cfg = StrategyConfig(st_period=period, st_multiplier=mult, timeframe_min=tf, moneyness=mny)
        if overrides:
            cfg = apply_overrides(cfg, overrides)
        rows.append(run_config(cfg, window, commission_fn))
        if i % 10 == 0 or i == len(combos):
            log.info("  %d/%d combos done", i, len(combos))

    print_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
