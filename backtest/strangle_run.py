"""Backtest runner for the bias-driven directional-strangle strategy.

Loads the window once (1m spot + option chains + India VIX) from Mongo, assembles per-bar
multi-timeframe ``BiasInputs`` via ``strangle_loader``, replays each day through
``strangle_sim.simulate_strangle_day``, and prints a per-day summary. With ``--trace`` it also
prints the detailed every-minute status (bias conditions, legs, P&L, action) for each day.

Usage:
  python backtest/strangle_run.py --days 30
  python backtest/strangle_run.py --config-file backtest/configs/strangle_premium.yaml --days 60
  python backtest/strangle_run.py --start 2026-06-20 --days 5 --trace
  python backtest/strangle_run.py --from 2021-06-01 --to 2026-05-31      # full-window walk
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient  # noqa: E402

from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator  # noqa: E402
from pdp.backtest.day_loader import biz_days, load_window  # noqa: E402
from pdp.backtest.strangle_config import StrangleConfig  # noqa: E402
from pdp.backtest.strangle_loader import build_strangle_day  # noqa: E402
from pdp.backtest.strangle_sim import BarStatus, format_status_line, simulate_strangle_day  # noqa: E402
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar  # noqa: E402
from pdp.settings import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("strangle")

_IST = timedelta(hours=5, minutes=30)
# India VIX index security id on Dhan (IDX_I). Override with --vix-sid / VIX_SECURITY_ID.
_DEFAULT_VIX_SID = os.getenv("VIX_SECURITY_ID", "21")


def load_vix_window(mdb, vix_sid: str, days: list[date]) -> dict[date, list[dict]]:
    """Load 1m India VIX bars from market_bars, bucketed by IST trade-date."""
    out: dict[date, list[dict]] = {}
    if not days:
        return out
    lo = datetime(days[0].year, days[0].month, days[0].day, 0, 0, tzinfo=UTC)
    hi = datetime(days[-1].year, days[-1].month, days[-1].day, 23, 59, tzinfo=UTC)
    for b in mdb["market_bars"].find(
        {"metadata.security_id": vix_sid, "metadata.timeframe": "1m",
         "ts": {"$gte": lo, "$lte": hi}}).sort("ts", 1):
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        out.setdefault((ts + _IST).date(), []).append(b)
    return out


def aggregate(results: list) -> dict:
    """Aggregate per-day DayResults into headline metrics (PF, win%, max DD)."""
    traded = [r for r in results if r is not None]
    gp = sum(r.realized for r in traded if r.realized >= 0)
    gl = sum(r.realized for r in traded if r.realized < 0)
    n = len(traded)
    pdays = sum(1 for r in traded if r.realized >= 0)
    eq = peak = max_dd = 0.0
    for r in traded:
        eq += r.realized
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    return {
        "days": n,
        "net": gp + gl,
        "gross_profit": gp,
        "gross_loss": gl,
        "profit_factor": (gp / abs(gl)) if gl else float("inf"),
        "win_rate": (pdays / n * 100) if n else 0.0,
        "max_dd": max_dd,
        "trades": sum(len(r.trades) for r in traded),
        "halted": sum(1 for r in traded if r.done_reason),
    }


def _parse_days(args) -> list[date]:
    """Resolve the trading-day window from --from/--to or --start/--days."""
    if args.from_date:
        start = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date) if args.to_date else _last_biz_day(date.today())
        out, d = [], start
        while d <= end:
            if d.weekday() < 5:
                out.append(d)
            d += timedelta(days=1)
        return out
    end = date.fromisoformat(args.start) if args.start else _last_biz_day(date.today())
    return biz_days(end, args.days or 30)


def _last_biz_day(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _print_summary(results: list, m: dict) -> None:
    print(f"\n{'='*92}")
    print(f"  DIRECTIONAL STRANGLE  —  {m['days']} traded days")
    print(f"{'='*92}")
    print(f"  {'Date':<12}  {'NIFTY Chg':>9}  {'Trades':>6}  {'Gross':>11}  {'Comm':>8}  {'Net':>11}  Status")
    print(f"  {'-'*12}  {'-'*9}  {'-'*6}  {'-'*11}  {'-'*8}  {'-'*11}  ------")
    for r in results:
        flag = "P" if r.realized >= 0 else "L"
        stp = f" {r.done_reason}" if r.done_reason else ""
        print(f"  {r.date:<12}  {r.nifty_chg:>+9.2f}  {len(r.trades):>6}  {r.gross_pnl:>+11.2f}  "
              f"{r.commission:>8.2f}  {r.realized:>+11.2f}  [{flag}]{stp}")
    pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    print(f"  {'-'*86}")
    print(f"  Net {m['net']:>+.0f}  |  PF {pf}  |  Win {m['win_rate']:.0f}%  |  "
          f"MaxDD {m['max_dd']:.0f}  |  Trades {m['trades']}  |  Halted {m['halted']}")
    print(f"{'='*92}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config-file", type=str, default=None, metavar="PATH",
                    help="StrangleConfig YAML (default: built-in defaults)")
    ap.add_argument("--days", type=int, default=None, help="Window size in trading days (default 30)")
    ap.add_argument("--start", type=str, default=None, help="End date YYYY-MM-DD (default last biz day)")
    ap.add_argument("--from", dest="from_date", type=str, default=None, help="Window start YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", type=str, default=None, help="Window end YYYY-MM-DD")
    ap.add_argument("--trace", action="store_true", help="Print the every-minute status trace per day")
    ap.add_argument("--vix-sid", type=str, default=_DEFAULT_VIX_SID, help="India VIX security id")
    ap.add_argument("--hedge", dest="hedge", action="store_true", default=None,
                    help="Force protective hedges ON (override config)")
    ap.add_argument("--no-hedge", dest="hedge", action="store_false",
                    help="Force protective hedges OFF (override config)")
    ap.add_argument("--no-commission", action="store_true")
    args = ap.parse_args()

    cfg = StrangleConfig.from_yaml(args.config_file) if args.config_file else StrangleConfig()
    if args.hedge is not None:
        cfg = StrangleConfig.from_dict({**cfg.to_dict(), "hedge_enabled": args.hedge})
    log.info("hedges: %s", "ON" if cfg.hedge_enabled else "OFF")

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

    days = _parse_days(args)
    log.info("loading window: %d biz days (%s .. %s)", len(days), days[0], days[-1])
    window = load_window(mdb, cal, days)
    vix_by_day = load_vix_window(mdb, args.vix_sid, days)
    log.info("window: %d valid days, %d skipped; VIX days: %d",
             len(window.valid_days), len(window.skipped), len(vix_by_day))
    if not window.valid_days:
        print("No valid trading days in window (run the Phase-0 backfill first).")
        return 1
    if not vix_by_day:
        log.warning("no India VIX data found for sid=%s — VIX gate will be inactive", args.vix_sid)

    results = []
    for d in window.valid_days:
        data = build_strangle_day(window, cfg, d, vix_by_day)
        if data is None:
            continue
        trace: list[BarStatus] | None = [] if args.trace else None
        r = simulate_strangle_day(cfg, data, commission_fn, trace=trace)
        if r is None:
            continue
        results.append(r)
        if trace is not None:
            print(f"\n----- {d} every-minute status -----")
            for st in trace:
                print("  " + format_status_line(st))

    if not results:
        print("No results (no decision bars / chain data in window).")
        return 1
    _print_summary(results, aggregate(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
