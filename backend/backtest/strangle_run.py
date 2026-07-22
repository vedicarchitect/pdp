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
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient  # noqa: E402

from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator  # noqa: E402
from pdp.backtest.day_loader import biz_days, load_window, warmup_prefix  # noqa: E402
from pdp.backtest.strangle_config import SECURITY_IDS, StrangleConfig, lot_size_for_date  # noqa: E402
from pdp.backtest.strangle_loader import build_strangle_day, load_pcr_window  # noqa: E402
from pdp.backtest.strangle_report import RunWriter  # noqa: E402
from pdp.backtest.strangle_sim import BarStatus, format_status_line, simulate_strangle_day  # noqa: E402
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar, within_dte  # noqa: E402
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


def _quarter_chunks(days: list[date]) -> list[list[date]]:
    """Group days by calendar quarter so multi-year runs load one quarter of chains at a time."""
    chunks: dict[tuple[int, int], list[date]] = {}
    for d in days:
        chunks.setdefault((d.year, (d.month - 1) // 3), []).append(d)
    return [chunks[k] for k in sorted(chunks)]


def _print_summary(results: list, m: dict, underlying: str = "NIFTY") -> None:
    chg_hdr = f"{underlying} Chg"
    print(f"\n{'='*92}")
    print(f"  DIRECTIONAL STRANGLE [{underlying}]  —  {m['days']} traded days")
    print(f"{'='*92}")
    print(f"  {'Date':<12}  {chg_hdr:>9}  {'Trades':>6}  {'Gross':>11}  {'Comm':>8}  {'Net':>11}  Status")
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
    ap.add_argument("--out-dir", type=str, default=None, metavar="DIR",
                    help="Archive per-day logs/trades/timing under DIR/<run_id>/ (e.g. backtest/runs)")
    ap.add_argument("--vix-sid", type=str, default=_DEFAULT_VIX_SID, help="India VIX security id")
    ap.add_argument("--hedge", dest="hedge", action="store_true", default=None,
                    help="Force protective hedges ON (override config)")
    ap.add_argument("--no-hedge", dest="hedge", action="store_false",
                    help="Force protective hedges OFF (override config)")
    ap.add_argument("--no-commission", action="store_true")
    ap.add_argument("--dte-max", dest="dte_max", type=int, default=None,
                    help="Only trade on days with calendar DTE <= this (0=expiry, 1=Mon for Tue-expiry)")
    ap.add_argument("--day-loss-limit", dest="day_loss_limit", type=float, default=None,
                    help="Daily loss cap in Rs before halt (default 15000; set 0 to disable)")
    ap.add_argument("--take-profit-pct", dest="take_profit_pct", type=float, default=None,
                    help="Close leg when this fraction of credit captured (default 0.5; set 0 to disable)")
    ap.add_argument("--neutral-trade", dest="neutral_trade", action="store_true", default=False,
                    help="Trade neutral bucket as 3PE:3CE symmetric strangle instead of skipping")
    ap.add_argument("--take-profit-extreme", dest="take_profit_extreme", action="store_true", default=False,
                    help="Apply take-profit only on complete_bull/bear legs; let balanced legs run to expiry")
    ap.add_argument("--scale-lots", dest="scale_lots", type=int, default=None,
                    help="Multiply all ratio_table lots by this factor (1=base, 2=double, 3=triple)")
    ap.add_argument("--mongo", dest="mongo", action="store_true", default=True,
                    help="Persist run/day/trade/decision docs to the MongoDB backtest warehouse "
                         "(DB-first; default ON — combine with --out-dir to additionally archive "
                         "local files)")
    ap.add_argument("--no-mongo", dest="mongo", action="store_false",
                    help="Skip Mongo persistence entirely (console-only run)")
    ap.add_argument("--no-vix-gate", dest="no_vix_gate", action="store_true", default=False,
                    help="Disable India VIX entry gate entirely (treat every bar as VIX-safe)")
    args = ap.parse_args()

    cfg = StrangleConfig.from_yaml(args.config_file) if args.config_file else StrangleConfig()
    if not getattr(cfg, "vix_gate_enabled", True):
        args.no_vix_gate = True
    if args.hedge is not None:
        cfg = StrangleConfig.from_dict({**cfg.to_dict(), "hedge_enabled": args.hedge})
    if args.dte_max is not None:
        cfg = StrangleConfig.from_dict({**cfg.to_dict(), "dte_max": args.dte_max})
    if args.day_loss_limit is not None:
        limit = args.day_loss_limit if args.day_loss_limit > 0 else 1e9
        cfg = StrangleConfig.from_dict({**cfg.to_dict(), "day_loss_limit": limit})
    if args.take_profit_pct is not None:
        tp = args.take_profit_pct if args.take_profit_pct > 0 else 999.0
        cfg = StrangleConfig.from_dict({**cfg.to_dict(), "take_profit_pct": tp})
    if args.neutral_trade:
        d = cfg.to_dict()
        d["neutral_no_trade"] = False
        d["ratio_table"]["neutral"] = [3, 3]
        cfg = StrangleConfig.from_dict(d)
    if args.take_profit_extreme:
        cfg = StrangleConfig.from_dict({**cfg.to_dict(), "take_profit_extreme_only": True})
    if args.scale_lots is not None:
        cfg = StrangleConfig.from_dict({**cfg.to_dict(), "scale_lots": args.scale_lots})
    dll = "OFF" if cfg.day_loss_limit >= 1e8 else f"Rs{cfg.day_loss_limit:,.0f}"
    tp = "OFF" if cfg.take_profit_pct >= 999 else f"{cfg.take_profit_pct*100:.0f}%"
    tp = f"{tp}·extreme-only" if cfg.take_profit_extreme_only else tp
    neutral = "3:3" if not cfg.neutral_no_trade else "skip"
    log.info("hedges: %s  vix_gate: %s  dte_max: %s  day_loss_limit: %s  take_profit: %s  neutral: %s  scale_lots: %s",
             "ON" if cfg.hedge_enabled else "OFF",
             "OFF" if args.no_vix_gate else "ON",
             cfg.dte_max if cfg.dte_max is not None else "ALL", dll, tp, neutral, cfg.scale_lots)

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]

    # Load the expiry calendar for the configured underlying.
    _cal_paths = {
        "NIFTY": s.EXPIRY_CACHE_PATH,
        "BANKNIFTY": s.BANKNIFTY_EXPIRY_CACHE_PATH,
        "SENSEX": s.SENSEX_EXPIRY_CACHE_PATH,
    }
    _cal_path = _cal_paths.get(cfg.underlying, s.EXPIRY_CACHE_PATH)
    try:
        cal = NiftyExpiryCalendar.load(_cal_path)
    except Exception as exc:
        cal = None
        log.warning("expiry calendar unavailable (%s); using %s weekday fallback",
                    exc, cfg.underlying)

    calc = NullCommissionCalculator(s.backtest_commission) if args.no_commission \
        else CommissionCalculator(s.backtest_commission)

    def commission_fn(side: str, turnover: float) -> float:
        return float(calc.calculate(side, Decimal(str(turnover))).total_inr)

    days = _parse_days(args)
    chunks = _quarter_chunks(days)
    log.info("window: %d biz days (%s .. %s) in %d quarter-chunks; hedges=%s out=%s",
             len(days), days[0], days[-1], len(chunks),
             "ON" if cfg.hedge_enabled else "OFF", args.out_dir or "-")

    # DB-first by default: --mongo alone is enough to persist to the warehouse. --out-dir
    # additionally switches the writer into the legacy local-folder archive mode.
    _mongo_store = None
    if args.mongo:
        from pdp.backtest.store import BacktestStore  # noqa: PLC0415
        _mc = MongoClient(s.MONGO_URI)
        _db = _mc[s.MONGO_DB_NAME]
        _mongo_store = BacktestStore(
            _db["backtest_runs"], _db["backtest_days"],
            _db["backtest_folds"], _db["backtest_trades"],
            col_sweeps=_db["backtest_sweeps"], col_decisions=_db["backtest_decisions"],
        )
    writer = (
        RunWriter(args.out_dir, cfg, store=_mongo_store, archive_local=bool(args.out_dir))
        if (args.out_dir or args.mongo) else None
    )
    # Full per-minute trace is only needed for --trace or legacy local-archive mode; DB-first
    # mode's default persistence is decision events, not the every-minute status log.
    want_trace = bool(args.trace) or (writer is not None and writer.archive_local)
    want_decisions = writer is not None
    if writer:
        writer.log(f"run start: {days[0]}..{days[-1]} ({len(days)} biz days, {len(chunks)} chunks)")

    results: list = []
    skipped = 0
    vix_days_seen = 0
    cadence_gap_total = 0
    for ci, chunk in enumerate(chunks, 1):
        # Spot-only warmup prefix: prior trading days before this chunk's first day so the
        # higher-TF EMAs are converged for the chunk's first traded day (not just for long
        # windows — every quarter-chunk boundary would otherwise start starved). See
        # bias-ranking-hardening.
        warmup_days = warmup_prefix(chunk)
        window = load_window(
            mdb, cal, chunk,
            security_id=cfg.security_id,
            underlying=cfg.underlying,
            warmup_days=warmup_days,
        )
        vix_by_day = {} if args.no_vix_gate else load_vix_window(mdb, args.vix_sid, chunk)
        vix_days_seen += len(vix_by_day)
        pcr_by_day = load_pcr_window(mdb["option_bars"], window.expiry_by_day, chunk,
                                     underlying=cfg.underlying)
        skipped += len(window.skipped)
        # Trade days resolved across a detected expiry-cadence gap (a missing, never-ingested
        # expiry) — surfaced separately from ordinary valid/skipped so a run doesn't need a
        # bespoke investigation to notice it silently traded (or phantom-skipped) against a
        # far-side expiry. See pdp.instruments.expiry_calendar.expiry_cadence_gaps.
        chunk_cadence_gap = len(window.cadence_gap_days & set(window.valid_days))
        cadence_gap_total += chunk_cadence_gap
        msg = (f"chunk {ci}/{len(chunks)} {chunk[0]}..{chunk[-1]} "
               f"(warmup from {warmup_days[0]}): "
               f"{len(window.valid_days)} valid, {len(window.skipped)} skipped, "
               f"{chunk_cadence_gap} cadence-gap, "
               f"VIX {len(vix_by_day)} PCR {len(pcr_by_day)}")
        log.info(msg)
        if writer:
            writer.log(msg)
        for d in window.valid_days:
            if not within_dte(d, window.expiry_by_day.get(d), cfg.dte_max):
                skipped += 1
                continue
            # Apply correct lot size for this trade date (changes over time per underlying).
            day_lot = lot_size_for_date(cfg.underlying, d)
            day_cfg = (cfg if day_lot == cfg.lot_size
                       else StrangleConfig.from_dict({**cfg.to_dict(), "lot_size": day_lot}))
            t0 = time.perf_counter()
            data = build_strangle_day(window, day_cfg, d, vix_by_day, pcr_by_day)
            build_ms = (time.perf_counter() - t0) * 1000.0
            if data is None:
                continue
            trace: list[BarStatus] | None = [] if want_trace else None
            decisions: list[dict] | None = [] if want_decisions else None
            t1 = time.perf_counter()
            r = simulate_strangle_day(day_cfg, data, commission_fn, trace=trace, decisions=decisions)
            sim_ms = (time.perf_counter() - t1) * 1000.0
            if r is None:
                continue
            results.append(r)
            if writer:
                writer.write_day(r, trace, build_ms, sim_ms, decisions=decisions)
            if args.trace:
                print(f"\n----- {d} every-minute status -----")
                for st in (trace or []):
                    print("  " + format_status_line(st))
        del window  # free this quarter's raw chains before loading the next

    if not vix_days_seen:
        log.warning("no India VIX data found for sid=%s — VIX gate was inactive", args.vix_sid)
    if cadence_gap_total:
        log.warning(
            "%d traded day(s) resolved to an expiry across a detected coverage gap "
            "(see chunk logs above)", cadence_gap_total,
        )
    if not results:
        print("No results (no decision bars / chain data in window).")
        return 1
    m = aggregate(results)
    _print_summary(results, m, cfg.underlying) if not writer else _print_summary_compact(results, m, cfg.underlying)
    if writer:
        out = writer.finalize(
            window={"from": str(days[0]), "to": str(days[-1]), "biz_days": len(days),
                    "traded_days": len(results), "skipped": skipped, "vix_days": vix_days_seen,
                    "cadence_gap_days": cadence_gap_total},
            metrics=m,
        )
        if out is not None:
            print(f"\nArtifacts: {out}")
            print("  summary.csv / equity.csv / manifest.json + days/<date>/"
                  "{status.log,trades.csv,legs.csv,day.json}")
        else:
            print(f"\nPersisted to warehouse: run_id={writer.run_id}")
    return 0


def _print_summary_compact(results: list, m: dict, underlying: str = "NIFTY") -> None:
    """Headline-only summary (the per-day detail is in the archived summary.csv)."""
    pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    print(f"\n{'='*92}")
    print(f"  DIRECTIONAL STRANGLE [{underlying}]  —  {m['days']} traded days")
    print(f"  Net {m['net']:>+.0f}  |  PF {pf}  |  Win {m['win_rate']:.0f}%  |  "
          f"MaxDD {m['max_dd']:.0f}  |  Trades {m['trades']}  |  Halted {m['halted']}")
    print(f"{'='*92}")


if __name__ == "__main__":
    raise SystemExit(main())
