"""Backtest runner for the intraday directional option-selling strategy.

Loads the window once (1m spot + option chains) from Mongo, assembles per-bar
``IntradayInputs`` via ``intraday_loader``, replays each day through
``intraday_sim.simulate_intraday_day``, and prints a per-day summary.

Deliberately mirrors ``strangle_run.py`` — same quarter-chunked load, same warmup prefix,
same ``RunWriter``/warehouse persistence, same ``aggregate()`` metric definitions — so a run
produced here is directly comparable with a directional-strangle run over the same window.

Usage:
  python backtest/intraday_run.py --days 30
  python backtest/intraday_run.py --config-file backtest/configs/intraday_nifty.yaml \
      --from 2023-01-06 --to 2026-07-25
  python backtest/intraday_run.py --start 2026-06-20 --days 3 --trace
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient  # noqa: E402

from backtest.strangle_run import (  # noqa: E402
    _parse_days,
    _quarter_chunks,
    aggregate,
)
from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator  # noqa: E402
from pdp.backtest.day_loader import load_window, warmup_prefix  # noqa: E402
from pdp.backtest.intraday_config import IntradayDirectionalConfig  # noqa: E402
from pdp.backtest.intraday_loader import build_intraday_day  # noqa: E402
from pdp.backtest.intraday_sim import IntradayBarStatus, simulate_intraday_day  # noqa: E402
from pdp.backtest.strangle_report import RunWriter  # noqa: E402
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar, within_dte  # noqa: E402
from pdp.settings import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("intraday")


def format_status_line(s: IntradayBarStatus) -> str:
    """Compact one-line IST status for every-bar logging."""
    pos = (
        f"-{s.lots}x{s.side}@{s.strike:.0f}"
        f"(e{s.avg_entry:.1f}/l{f'{s.ltp:.1f}' if s.ltp is not None else '-'})"
        if s.side else "flat"
    )
    vwap = f"{s.session_vwap:.1f}" if s.session_vwap is not None else "-"
    orb = (
        f"{s.orb_low:.0f}-{s.orb_high:.0f}"
        if s.orb_high is not None and s.orb_low is not None else "-"
    )
    st = "-" if s.st_dir is None else f"{s.st_dir:+d}"
    ost = "-" if s.option_st_dir is None else f"{s.option_st_dir:+d}"
    return (
        f"{s.ist_dt:%H:%M} spot={s.spot:.1f} vwap={vwap} orb={orb} st={st} ost={ost} "
        f"brk={s.ema_break_bars} cam={s.cam_reject_bars} | {pos} | "
        f"day={s.day_pnl:+.0f} | {s.action}"
    )


def _print_summary(results: list, m: dict, underlying: str) -> None:
    chg_hdr = f"{underlying} Chg"
    print(f"\n{'='*92}")
    print(f"  INTRADAY DIRECTIONAL [{underlying}]  —  {m['days']} traded days")
    print(f"{'='*92}")
    print(f"  {'Date':<12}  {chg_hdr:>9}  {'Trades':>6}  {'Gross':>11}  {'Comm':>8}  "
          f"{'Net':>11}  Status")
    print(f"  {'-'*12}  {'-'*9}  {'-'*6}  {'-'*11}  {'-'*8}  {'-'*11}  ------")
    for r in results:
        flag = "P" if r.realized >= 0 else "L"
        stp = f" {r.done_reason}" if r.done_reason else ""
        print(f"  {r.date:<12}  {r.nifty_chg:>+9.2f}  {len(r.trades):>6}  {r.gross_pnl:>+11.2f}  "
              f"{r.commission:>8.2f}  {r.realized:>+11.2f}  [{flag}]{stp}")
    _print_metrics(m)


def _print_summary_compact(results: list, m: dict, underlying: str) -> None:
    print(f"\n  INTRADAY DIRECTIONAL [{underlying}]  —  {m['days']} traded days")
    _print_metrics(m)


def _print_metrics(m: dict) -> None:
    pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    print(f"  {'-'*86}")
    print(f"  Net {m['net']:>+.0f}  |  PF {pf}  |  Win {m['win_rate']:.0f}%  |  "
          f"MaxDD {m['max_dd']:.0f}  |  Trades {m['trades']}  |  Halted {m['halted']}")
    print(f"{'='*92}\n")


def _apply_overrides(cfg: IntradayDirectionalConfig, args) -> IntradayDirectionalConfig:
    """Apply CLI overrides onto the loaded config, one rebuild per flag so each is validated."""
    overrides: dict = {}
    if args.hedge is not None:
        overrides["hedge_enabled"] = args.hedge
    if args.dte_max is not None:
        overrides["dte_max"] = args.dte_max
    if args.moneyness is not None:
        overrides["moneyness"] = args.moneyness
    if args.day_loss_limit is not None:
        overrides["day_loss_limit"] = args.day_loss_limit if args.day_loss_limit > 0 else 1e9
    if args.unreal_loss_pct is not None:
        overrides["unreal_loss_pct"] = args.unreal_loss_pct if args.unreal_loss_pct > 0 else 999.0
    if args.max_lots is not None:
        overrides["max_lots"] = args.max_lots
    if args.no_roll:
        overrides["roll_enabled"] = False
    if args.underlying is not None:
        overrides["underlying"] = args.underlying
        # Let from_dict re-derive the matching security_id / strike_step.
        base = cfg.to_dict()
        base.pop("security_id", None)
        base.pop("strike_step", None)
        return IntradayDirectionalConfig.from_dict({**base, **overrides})
    if not overrides:
        return cfg
    return IntradayDirectionalConfig.from_dict({**cfg.to_dict(), **overrides})


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config-file", type=str, default=None, metavar="PATH",
                    help="IntradayDirectionalConfig YAML (defaults to built-in defaults)")
    ap.add_argument("--underlying", type=str, default=None,
                    choices=["NIFTY", "BANKNIFTY", "SENSEX"])
    ap.add_argument("--days", type=int, default=None, help="N trading days ending at --start")
    ap.add_argument("--start", type=str, default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--from", dest="from_date", type=str, default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", type=str, default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--trace", action="store_true", help="print every-bar status per day")
    ap.add_argument("--out-dir", type=str, default=None,
                    help="also archive a local run folder (legacy)")
    ap.add_argument("--no-commission", action="store_true")
    ap.add_argument("--dte-max", type=int, default=None)
    ap.add_argument("--moneyness", type=int, default=None,
                    help="0=ATM, negative=ITM, positive=OTM")
    ap.add_argument("--max-lots", type=int, default=None)
    ap.add_argument("--day-loss-limit", type=float, default=None, help="0 disables")
    ap.add_argument("--unreal-loss-pct", type=float, default=None, help="0 disables")
    ap.add_argument("--hedge", dest="hedge", action="store_true", default=None)
    ap.add_argument("--no-hedge", dest="hedge", action="store_false")
    ap.add_argument("--no-roll", action="store_true", help="disable rollup-to-ATM")
    ap.add_argument("--mongo", dest="mongo", action="store_true", default=True)
    ap.add_argument("--no-mongo", dest="mongo", action="store_false")
    args = ap.parse_args()

    cfg = (
        IntradayDirectionalConfig.from_yaml(args.config_file)
        if args.config_file else IntradayDirectionalConfig()
    )
    cfg = _apply_overrides(cfg, args)

    dll = "OFF" if cfg.day_loss_limit >= 1e8 else f"Rs{cfg.day_loss_limit:,.0f}"
    uls = "OFF" if cfg.unreal_loss_pct >= 999 else f"{cfg.unreal_loss_pct*100:.0f}%"
    log.info(
        "underlying: %s  moneyness: %s  lots: %d->%d/%dm  dte_max: %s  day_loss: %s  "
        "unreal_stop: %s  prem_stop: %.0f%%  roll: %s  hedge: %s  vwap: %s",
        cfg.underlying, cfg.moneyness, cfg.initial_lots, cfg.max_lots, cfg.scale_in_minutes,
        cfg.dte_max if cfg.dte_max is not None else "ALL", dll, uls,
        cfg.premium_rise_stop_pct * 100,
        f"ON<{cfg.roll_trigger_prem:.0f}->ATM>={cfg.roll_target_min_prem:.0f}"
        if cfg.roll_enabled else "OFF",
        "ON" if cfg.hedge_enabled else "OFF", cfg.vwap_source,
    )

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]

    _cal_paths = {
        "NIFTY": s.EXPIRY_CACHE_PATH,
        "BANKNIFTY": s.BANKNIFTY_EXPIRY_CACHE_PATH,
        "SENSEX": s.SENSEX_EXPIRY_CACHE_PATH,
    }
    try:
        cal = NiftyExpiryCalendar.load(_cal_paths.get(cfg.underlying, s.EXPIRY_CACHE_PATH))
    except Exception as exc:
        cal = None
        log.warning("expiry calendar unavailable (%s); resolving expiries from option_bars", exc)

    calc = (NullCommissionCalculator(s.backtest_commission) if args.no_commission
            else CommissionCalculator(s.backtest_commission))

    def commission_fn(side: str, turnover: float) -> float:
        return float(calc.calculate(side, Decimal(str(turnover))).total_inr)

    days = _parse_days(args)
    if not days:
        print("No trading days in window.")
        return 1
    chunks = _quarter_chunks(days)
    log.info("window: %d biz days (%s .. %s) in %d quarter-chunks",
             len(days), days[0], days[-1], len(chunks))

    _mongo_store = None
    if args.mongo:
        from pdp.backtest.store import BacktestStore
        _db = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
        _mongo_store = BacktestStore(
            _db["backtest_runs"], _db["backtest_days"],
            _db["backtest_folds"], _db["backtest_trades"],
            col_sweeps=_db["backtest_sweeps"], col_decisions=_db["backtest_decisions"],
        )
    run_id = f"intraday_{time.strftime('%Y%m%d-%H%M%S')}"
    writer = (
        RunWriter(args.out_dir, cfg, run_id=run_id, store=_mongo_store,
                  archive_local=bool(args.out_dir))
        if (args.out_dir or args.mongo) else None
    )
    want_trace = bool(args.trace) or (writer is not None and writer.archive_local)
    want_decisions = writer is not None
    if writer:
        writer.log(f"run start: {days[0]}..{days[-1]} ({len(days)} biz days, {len(chunks)} chunks)")

    results: list = []
    skipped = 0
    cadence_gap_total = 0
    no_orb_days = 0
    for ci, chunk in enumerate(chunks, 1):
        warmup_days = warmup_prefix(chunk)
        window = load_window(
            mdb, cal, chunk,
            security_id=cfg.security_id,
            underlying=cfg.underlying,
            warmup_days=warmup_days,
        )
        skipped += len(window.skipped)
        chunk_cadence_gap = len(window.cadence_gap_days & set(window.valid_days))
        cadence_gap_total += chunk_cadence_gap
        msg = (f"chunk {ci}/{len(chunks)} {chunk[0]}..{chunk[-1]} "
               f"(warmup from {warmup_days[0]}): "
               f"{len(window.valid_days)} valid, {len(window.skipped)} skipped, "
               f"{chunk_cadence_gap} cadence-gap")
        log.info(msg)
        if writer:
            writer.log(msg)
        for d in window.valid_days:
            if not within_dte(d, window.expiry_by_day.get(d), cfg.dte_max):
                skipped += 1
                continue
            day_cfg = cfg.for_date(d)
            t0 = time.perf_counter()
            data = build_intraday_day(window, day_cfg, d)
            build_ms = (time.perf_counter() - t0) * 1000.0
            if data is None:
                continue
            if data.orb_high is None:
                # No 09:15-stamped candle for this session — the opening range never
                # formed, so entries are blocked. Counted, never silently traded.
                no_orb_days += 1
                continue
            trace: list[IntradayBarStatus] | None = [] if want_trace else None
            decisions: list[dict] | None = [] if want_decisions else None
            t1 = time.perf_counter()
            r = simulate_intraday_day(day_cfg, data, commission_fn, trace=trace,
                                      decisions=decisions)
            sim_ms = (time.perf_counter() - t1) * 1000.0
            if r is None:
                continue
            results.append(r)
            if writer:
                writer.write_day(r, trace, build_ms, sim_ms, decisions=decisions)
            if args.trace:
                print(f"\n----- {d} every-bar status -----")
                for st in (trace or []):
                    print("  " + format_status_line(st))
        del window

    if cadence_gap_total:
        log.warning(
            "%d traded day(s) resolved to an expiry across a detected coverage gap "
            "(see chunk logs above)", cadence_gap_total,
        )
    if no_orb_days:
        log.warning("%d day(s) skipped: no %s opening-range candle",
                    no_orb_days, cfg.orb_start_ist.strftime("%H:%M"))
    if not results:
        print("No results (no decision bars / chain data in window).")
        return 1

    m = aggregate(results)
    if writer:
        _print_summary_compact(results, m, cfg.underlying)
    else:
        _print_summary(results, m, cfg.underlying)
    if writer:
        out = writer.finalize(
            window={"from": str(days[0]), "to": str(days[-1]), "biz_days": len(days),
                    "traded_days": len(results), "skipped": skipped,
                    "no_orb_days": no_orb_days, "cadence_gap_days": cadence_gap_total},
            metrics=m,
        )
        if out is not None:
            print(f"\nArtifacts: {out}")
        else:
            print(f"\nPersisted to warehouse: run_id={writer.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
