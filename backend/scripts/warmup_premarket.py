"""Pre-market prechecks + warmup: run the same seeding sequence the engine does at
boot, standalone, before the trading process starts.

This makes indicator warmup independent of the trading process's own startup path —
run it minutes before the session opens (or after any gap: a restart, a few hours
down, a fresh boot after days off) and the trading process then finds `market_bars`
and the indicator matrix already correct, instead of doing this work cold on its own
critical boot path.

Reuses exactly what `pdp.runtime.groups` (FeedEngineGroup) does at boot:
  1. Build an `IndicatorEngine`, configure every strategy's watchlist suites.
  2. `configure_matrix_suites` — Execution-tab matrix (spot + front-month futures).
  3. `warm_up_indicator_engine` — now reconciles derivable timeframes (15m/30m/1H)
     against the 1-minute series unconditionally (`bar-warmup-reconcile-from-1m`),
     so a corrupt store (duplicates/gaps from a feed outage) self-heals here too,
     not only depth shortfalls.
  4. Publish `matrix:futures_sids` to Redis (same key `pdp-api` reads).
  5. `compute_session_levels` — Camarilla/pivot levels from the prior session.
  6. Log `indicator_seeding_summary` per strategy — same line the engine emits,
     so "did warmup actually converge" is answerable without starting the engine.

Market-hours awareness: intended to run pre-market (before 09:15 IST). Warmup itself
never depends on the live WS feed — it reads `market_bars` (already backfilled ~5yr
of 1m) and falls back to a chunked Dhan REST call only when 1m coverage is itself
missing (`indicator-warmup-derive-from-1m`). So this script works identically whether
run pre-market, mid-day, or after the process has been down for days; the only
market-hours-specific behavior is the `--allow-market-hours` gate below, which exists
to stop this from being run as a surprise mid-session reload against a live strategy.

Usage:
    uv run python scripts/warmup_premarket.py
    uv run python scripts/warmup_premarket.py --allow-market-hours   # ops override
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guard_market_hours import is_market_hours

from pdp.indicators.engine import IndicatorEngine
from pdp.indicators.warmup import (
    configure_matrix_suites,
    premarket_marker_key,
    warm_up_indicator_engine,
)
from pdp.mongo.client import connect as mongo_connect
from pdp.mongo.client import disconnect as mongo_disconnect
from pdp.options.gap_backfill import holidays as load_holidays
from pdp.settings import get_settings
from pdp.strategy.registry import load_all

log = structlog.get_logger()
_IST = ZoneInfo("Asia/Kolkata")


async def run(*, allow_market_hours: bool) -> int:
    settings = get_settings()
    holiday_set = load_holidays(settings.NSE_HOLIDAYS_JSON)
    now_ist = datetime.now(_IST)

    if is_market_hours(now_ist, holiday_set) and not allow_market_hours:
        log.warning(
            "warmup_premarket_refused_market_hours",
            now_ist=now_ist.isoformat(),
            hint="pass --allow-market-hours to force a mid-session reseed",
        )
        return 1

    mongo_client, mongo_db = mongo_connect(settings)
    try:
        engine = IndicatorEngine(
            st_period=settings.SUPERTREND_PERIOD,
            st_multiplier=settings.SUPERTREND_MULTIPLIER,
        )

        all_configs = load_all(Path("strategies"))
        watchlist_dicts: list[dict] = [
            {
                "security_id": w.security_id,
                "exchange_segment": w.exchange_segment,
                "timeframes": w.timeframes,
                "indicators": w.indicators,
            }
            for cfg in all_configs
            for w in cfg.watchlist
        ]
        for cfg in all_configs:
            for w in cfg.watchlist:
                if w.indicators:
                    for tf in w.timeframes:
                        engine.configure_suite(w.security_id, tf, w.indicators)

        from pdp.db.session import dispose_engine, get_session_maker

        try:
            matrix_entries = await configure_matrix_suites(engine, get_session_maker())
            watchlist_dicts.extend(matrix_entries)
        except Exception as exc:
            log.warning("warmup_premarket_matrix_suites_failed", exc=str(exc))
        finally:
            await dispose_engine()

        if watchlist_dicts:
            # reconcile=True: this standalone premarket job owns the write-heavy
            # derive-from-1m reconcile (deep higher-timeframe history). The trading
            # process boots read-only (reconcile=False) and never pays this on its
            # critical path — see warmup-decouple directive.
            await warm_up_indicator_engine(
                engine, mongo_db, settings, watchlist_dicts, reconcile=True
            )

        # Publish the same key pdp-api's indicator matrix reads when it has no
        # in-process engine (split-process deployment) — see groups.py.
        try:
            import json

            from redis import asyncio as redis_asyncio

            redis = redis_asyncio.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                await redis.set(
                    "matrix:futures_sids", json.dumps(engine.matrix_futures_sids), ex=86400
                )
            finally:
                await redis.aclose()
        except Exception as exc:
            log.warning("warmup_premarket_redis_publish_failed", exc=str(exc))

        try:
            from pdp.indicators.levels_store import compute_session_levels

            await compute_session_levels(
                mongo_db,
                security_ids=["13", "25", "51"],
                holiday_json=settings.NSE_HOLIDAYS_JSON,
            )
            log.info("warmup_premarket_session_levels_computed")
        except Exception as exc:
            log.warning("warmup_premarket_session_levels_failed", exc=str(exc))

        unseeded_total = 0
        for cfg in all_configs:
            unseeded: list[dict] = []
            for w in cfg.watchlist:
                for tf in w.timeframes:
                    for (family, period), seeded in engine.seeding_summary(w.security_id, tf).items():
                        if not seeded:
                            unseeded.append(
                                {"security_id": w.security_id, "timeframe": tf, "family": family, "period": period}
                            )
            log.info(
                "indicator_seeding_summary",
                strategy_id=cfg.id,
                unseeded_count=len(unseeded),
                unseeded=unseeded,
            )
            unseeded_total += len(unseeded)

        # Record that the premarket job ran today so the execution panel's Premarket
        # readiness badge clears (warmup-decouple directive). Keyed by IST date, 24h TTL.
        try:
            import json

            from redis import asyncio as redis_asyncio

            ist_date = datetime.now(_IST).date()
            redis = redis_asyncio.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                await redis.set(
                    premarket_marker_key(ist_date),
                    json.dumps(
                        {
                            "ran_at": datetime.now(_IST).isoformat(),
                            "unseeded_total": unseeded_total,
                        }
                    ),
                    ex=86400,
                )
            finally:
                await redis.aclose()
        except Exception as exc:
            log.warning("warmup_premarket_marker_failed", exc=str(exc))

        log.info("warmup_premarket_done", unseeded_total=unseeded_total)
        return 1 if unseeded_total else 0
    finally:
        mongo_disconnect(mongo_client)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--allow-market-hours",
        action="store_true",
        help="Force a reseed even during a live trading session (09:15-15:30 IST).",
    )
    args = ap.parse_args()
    return asyncio.run(run(allow_market_hours=args.allow_market_hours))


if __name__ == "__main__":
    sys.exit(main())
