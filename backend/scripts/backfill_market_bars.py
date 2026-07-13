"""Backfill `market_bars` to the depth `indicator-history-depth` requires.

For every underlying declared by a loaded strategy's `params.underlying`
(`pdp.strategy.registry.strategy_underlyings`) x that underlying's
live-configured derivable timeframe (15m/30m/1H), ensure at least
`required_bars(indicators)` bars exist
(~1200 at the period-200 EMA setting `indicator-history-depth` added to the live
strangle configs). Reuses the two existing implementations rather than adding a
third:
  - `scripts/oneoff/rebuild_market_bars.py`'s `rollup_bars()` derives 15m/30m/1H
    from the stored 1m series via `_bar_boundary` -- the same session-anchored
    bucket function the live `BarAggregator` uses.
  - `scripts/backfill_spot.py`'s `_fetch_chunk`/`_write_day` top up 1m itself via
    Dhan wherever 1m coverage is the thing actually missing (not just the
    derived timeframe) -- used only as a fallback, per the spec requirement
    that backfill prefer deriving from 1m and never call Dhan when it doesn't
    have to.

Usage:
    uv run python scripts/backfill_market_bars.py --dry-run
    uv run python scripts/backfill_market_bars.py --to 2026-07-11
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR / "oneoff"))

from pdp.indicators.warmup import required_bars  # noqa: E402
from pdp.options.gap_backfill import holidays, trading_days  # noqa: E402
from pdp.settings import get_settings  # noqa: E402
from pdp.strategy.registry import load_all, strategy_underlyings  # noqa: E402
from pdp.warehouse.service import SID_MAP  # noqa: E402

log = structlog.get_logger()

_DERIVABLE_TFS: dict[str, int] = {"15m": 15, "30m": 30, "1H": 60}
_SESSION_BARS = 375  # full 09:15-15:30 session, matches backfill_spot.py's EXPECTED_BARS
_ONLY_MISSING_FRAC = 0.95


def _watchlist_entry(underlying: str) -> tuple[list[dict[str, Any]], list[str]]:
    """The live strategy's configured indicators + timeframes for this underlying.

    Reads the same `strategies/directional_strangle_<u>.yaml` the live
    `StrategyHost` loads, so backfill depth always tracks the real config
    instead of a second hand-maintained period list.
    """
    strategy_id = f"directional_strangle_{underlying.lower()}"
    for cfg in load_all(Path("strategies")):
        if cfg.id != strategy_id:
            continue
        for w in cfg.watchlist:
            if w.security_id == SID_MAP[underlying]:
                return w.indicators, w.timeframes
    return [], list(_DERIVABLE_TFS)


def _load_1m_bars(col: Any, security_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    cursor = col.find(
        {"metadata.security_id": security_id, "metadata.timeframe": "1m", "ts": {"$gte": start, "$lt": end}}
    ).sort("ts", 1)
    return list(cursor)


def _count(col: Any, security_id: str, tf: str, start: datetime, end: datetime) -> int:
    return col.count_documents(
        {"metadata.security_id": security_id, "metadata.timeframe": tf, "ts": {"$gte": start, "$lt": end}}
    )


def _ensure_1m_coverage(
    col: Any, dhan: Any, security_id: str, start_d: date, end_d: date, holiday_set: set[date]
) -> list[date]:
    """Top up 1m coverage via Dhan for any trading day short of a full session.

    Returns the list of days that actually required a Dhan fetch (for logging
    "which windows required it", per task 5.3). No-op (returns []) if 1m is
    already dense or Dhan credentials are unavailable.
    """
    from backfill_spot import (  # type: ignore[import-not-found]
        _chunks,
        _existing_count,
        _fetch_chunk,
        _write_day,
    )

    if dhan is None:
        return []
    days = trading_days(start_d, end_d, holiday_set)
    threshold = int(_SESSION_BARS * _ONLY_MISSING_FRAC)
    missing = [d for d in days if _existing_count(col, d, security_id) < threshold]
    if not missing:
        return []
    log.info("indicator_backfill_1m_gap_dhan_fallback", security_id=security_id, missing_days=len(missing))
    missing_set = set(missing)
    for from_d, to_d in _chunks(missing, 90):
        docs = _fetch_chunk(dhan, from_d, to_d, security_id)
        by_day: dict[date, list[dict[str, Any]]] = {}
        for d in docs:
            ist_day = (d["ts"] + timedelta(hours=5, minutes=30)).date()
            if ist_day in missing_set:
                by_day.setdefault(ist_day, []).append(d)
        for day, day_docs in sorted(by_day.items()):
            _write_day(col, day, day_docs, security_id)
    return missing


def run(*, to_d: date, dry_run: bool) -> tuple[int, list[dict[str, Any]]]:
    """Returns (exit_code, per-(sid, tf) result rows) for the caller to print/record."""
    from pymongo import MongoClient
    from rebuild_market_bars import rollup_bars  # type: ignore[import-not-found]

    settings = get_settings()
    dhan = None
    if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        from dhanhq import DhanContext, dhanhq

        dhan = dhanhq(DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN))
    holiday_set = holidays(settings.NSE_HOLIDAYS_JSON)
    col = MongoClient(settings.MONGO_URI)[settings.MONGO_DB_NAME]["market_bars"]

    end = datetime(to_d.year, to_d.month, to_d.day, tzinfo=UTC) + timedelta(days=1)
    results: list[dict[str, Any]] = []
    shortfalls: list[dict[str, Any]] = []

    for underlying in sorted(strategy_underlyings(Path("strategies"))):
        if underlying not in SID_MAP:
            log.warning("indicator_backfill_unknown_underlying", underlying=underlying)
            continue
        sid = SID_MAP[underlying]
        indicators, timeframes = _watchlist_entry(underlying)
        needed = required_bars(indicators)
        # Generous calendar window: worst case (1D bars) needs ~needed calendar days;
        # intraday timeframes need far fewer, so this always overshoots wide enough.
        start_d = to_d - timedelta(days=needed * 2)
        start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=UTC)

        for tf in (t for t in timeframes if t in _DERIVABLE_TFS):
            found = _count(col, sid, tf, start, end)
            if found >= needed:
                log.info("indicator_backfill_depth_met", underlying=underlying, timeframe=tf,
                          found=found, needed=needed)
                results.append({"underlying": underlying, "security_id": sid, "timeframe": tf,
                                 "found": found, "needed": needed, "action": "none"})
                continue

            log.info("indicator_backfill_depth_short", underlying=underlying, timeframe=tf,
                      found=found, needed=needed)
            action = "dry_run"
            if not dry_run:
                filled_days = _ensure_1m_coverage(col, dhan, sid, start_d, to_d, holiday_set)
                bars_1m = _load_1m_bars(col, sid, start, end)
                tf_minutes = _DERIVABLE_TFS[tf]
                new_docs = rollup_bars(bars_1m, tf_minutes, tf)
                if new_docs:
                    col.delete_many({"metadata.security_id": sid, "metadata.timeframe": tf,
                                      "ts": {"$gte": start, "$lt": end}})
                    col.insert_many(new_docs, ordered=False)
                found = len(new_docs)
                action = "dhan_then_rollup" if filled_days else "rollup_from_1m"

            row = {"underlying": underlying, "security_id": sid, "timeframe": tf,
                   "found": found, "needed": needed, "action": action}
            results.append(row)
            if found < needed:
                shortfalls.append(row)

    for s in shortfalls:
        log.error("indicator_backfill_shortfall", **s)
    return (1 if shortfalls else 0), results


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", dest="to_d", type=_parse_date, default=date.today())
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    exit_code, results = run(to_d=args.to_d, dry_run=args.dry_run)
    for row in results:
        print(f"{row['underlying']:<10} {row['timeframe']:<4} found={row['found']:<6} "
              f"needed={row['needed']:<6} action={row['action']}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
