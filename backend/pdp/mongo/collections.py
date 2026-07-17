from __future__ import annotations

import structlog
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import CollectionInvalid

from pdp.settings import Settings

log = structlog.get_logger()


async def init_collections(db: AsyncIOMotorDatabase, settings: Settings) -> None:  # type: ignore[type-arg]
    await _ensure_market_bars(db)
    await _ensure_expired_option_bars(db)
    await _ensure_option_bars(db)
    await _ensure_option_chains(db, settings.MONGO_CHAIN_TTL_DAYS, settings.OPTIONS_CHAIN_TTL_DAYS)
    await _ensure_oi_snapshots(db)
    await _ensure_portfolio_snapshots(db)
    await _ensure_advisory_snapshots(db)
    await _ensure_positional_eod_snapshots(db)
    await _ensure_broker_snapshots(db)
    await _ensure_backtest_runs(db)
    await _ensure_backtest_days(db)
    await _ensure_backtest_folds(db)
    await _ensure_backtest_trades(db)
    await _ensure_backtest_sweeps(db)
    await _ensure_backtest_decisions(db)
    await _ensure_backtest_promotions(db)
    await _ensure_index_levels(db)
    await _ensure_events(db, settings.EVENTS_TTL_DAYS)
    await _ensure_expiry_calendar(db)


async def _ensure_market_bars(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    try:
        await db.create_collection(
            "market_bars",
            timeseries={
                "timeField": "ts",
                "metaField": "metadata",
                "granularity": "seconds",
            },
        )
        log.info("mongo_collection_created", collection="market_bars")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="market_bars")


async def _ensure_expired_option_bars(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Time-series store for ATM-relative bars of expired option contracts.

    Keyed by ATM-relative label (not security_id) because the rolling-option API
    re-evaluates ATM per bar. metadata distinguishes the rolling series:
    underlying / expiry_flag / expiry_code / strike_label / option_type / timeframe.
    """
    try:
        await db.create_collection(
            "expired_option_bars",
            timeseries={
                "timeField": "ts",
                "metaField": "metadata",
                "granularity": "seconds",
            },
        )
        log.info("mongo_collection_created", collection="expired_option_bars")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="expired_option_bars")


async def _ensure_option_bars(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Unified options warehouse keyed by the real fixed contract.

    A **regular** (non-time-series) collection — Mongo time-series collections cannot carry a
    unique index, and we need DB-enforced dedup so the live feed and backfill can both write
    without ever creating duplicate bars. Keyed by
    ``(underlying, expiry_date, strike, option_type, timeframe, ts)``.
    """
    try:
        await db.create_collection("option_bars")
        log.info("mongo_collection_created", collection="option_bars")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="option_bars")

    col = db["option_bars"]
    # Unique contract+ts key: makes duplicate bars structurally impossible across producers.
    await col.create_index(
        [
            ("underlying", ASCENDING),
            ("expiry_date", ASCENDING),
            ("strike", ASCENDING),
            ("option_type", ASCENDING),
            ("timeframe", ASCENDING),
            ("ts", ASCENDING),
        ],
        unique=True,
        name="uq_contract_ts",
    )
    # Read paths: by expiry (whole chain for a day) and by strike (a fixed-strike series).
    await col.create_index(
        [("underlying", ASCENDING), ("expiry_date", ASCENDING), ("option_type", ASCENDING),
         ("ts", ASCENDING)],
        name="idx_expiry_optype_ts",
    )
    await col.create_index(
        [("underlying", ASCENDING), ("strike", ASCENDING), ("option_type", ASCENDING),
         ("ts", ASCENDING)],
        name="idx_strike_optype_ts",
    )
    # Read path: coverage check / gaps (by underlying + timeframe across time)
    await col.create_index(
        [("underlying", ASCENDING), ("timeframe", ASCENDING), ("ts", ASCENDING)],
        name="idx_underlying_tf_ts",
    )
    # Read path: a single contract's own 1m series by security_id (the ATM CE/PE
    # indicator suite, `pdp.strategy.atm_suite`). None of the indexes above lead with
    # security_id, so that query previously fell back to a full collection scan across
    # the whole warehouse (tens of millions of docs) and tripped socketTimeoutMS.
    await col.create_index(
        [("security_id", ASCENDING), ("timeframe", ASCENDING), ("ts", ASCENDING)],
        name="idx_security_tf_ts",
    )


async def _ensure_option_chains(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    legacy_ttl_days: int,
    snapshot_ttl_days: int,
) -> None:
    try:
        await db.create_collection("option_chains")
        log.info("mongo_collection_created", collection="option_chains")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="option_chains")

    # create_index is idempotent when name+spec match. Changing TTL values on an
    # existing deployment has no effect until the old index is dropped manually.
    await db["option_chains"].create_index(
        [("captured_at", ASCENDING)],
        expireAfterSeconds=legacy_ttl_days * 86400,
        name="ttl_captured_at",
    )
    await db["option_chains"].create_index(
        [("snapshot_ts", ASCENDING)],
        expireAfterSeconds=snapshot_ttl_days * 86400,
        name="ttl_snapshot_ts",
    )
    await db["option_chains"].create_index(
        [("underlying", ASCENDING), ("expiry", ASCENDING), ("snapshot_ts", DESCENDING)],
        name="idx_underlying_expiry_snapshot",
    )


async def _ensure_oi_snapshots(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Time-series store for intraday ATM-relative OI snapshots (every ~5 min).

    One document per (symbol, snapshot) carrying the ATM +/- N strikes' CE/PE OI plus the
    events derived against the morning baseline. metadata = underlying symbol + expiry so a
    whole day's series for one index reads back in time order.
    """
    try:
        await db.create_collection(
            "oi_snapshots",
            timeseries={
                "timeField": "ts",
                "metaField": "metadata",
                "granularity": "minutes",
            },
        )
        log.info("mongo_collection_created", collection="oi_snapshots")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="oi_snapshots")


async def _ensure_portfolio_snapshots(db: AsyncIOMotorDatabase, ttl_days: int = 90) -> None:  # type: ignore[type-arg]
    try:
        await db.create_collection("portfolio_snapshots")
        log.info("mongo_collection_created", collection="portfolio_snapshots")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="portfolio_snapshots")

    await db["portfolio_snapshots"].create_index(
        [("snapshot_ts", ASCENDING)],
        expireAfterSeconds=ttl_days * 86400,
        name="ttl_snapshot_ts",
    )
    await db["portfolio_snapshots"].create_index(
        [("snapshot_date", ASCENDING)],
        unique=True,
        name="uq_snapshot_date",
    )


async def _ensure_advisory_snapshots(db: AsyncIOMotorDatabase, ttl_days: int = 90) -> None:  # type: ignore[type-arg]
    """Audit trail of computed portfolio-advisory results (holdings + advice)."""
    try:
        await db.create_collection("advisory_snapshots")
        log.info("mongo_collection_created", collection="advisory_snapshots")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="advisory_snapshots")

    await db["advisory_snapshots"].create_index(
        [("snapshot_ts", ASCENDING)],
        expireAfterSeconds=ttl_days * 86400,
        name="ttl_snapshot_ts",
    )


async def _ensure_positional_eod_snapshots(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    try:
        await db.create_collection("positional_eod_snapshots")
        log.info("mongo_collection_created", collection="positional_eod_snapshots")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="positional_eod_snapshots")

    await db["positional_eod_snapshots"].create_index(
        [("date", ASCENDING)],
        unique=True,
        name="uq_date",
    )


async def _ensure_broker_snapshots(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Immutable daily archive of Dhan-reported account records.

    One regular document per (account_id, snapshot_date, report_type) where
    report_type ∈ {holdings, positions, funds, orders, trades, ledger}. Regular (not
    time-series) so it supports idempotent upsert by the unique key.
    """
    try:
        await db.create_collection("broker_snapshots")
        log.info("mongo_collection_created", collection="broker_snapshots")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="broker_snapshots")

    col = db["broker_snapshots"]
    await col.create_index(
        [("account_id", ASCENDING), ("snapshot_date", ASCENDING), ("report_type", ASCENDING)],
        unique=True,
        name="uq_account_date_report",
    )
    await col.create_index(
        [("account_id", ASCENDING), ("report_type", ASCENDING), ("snapshot_date", DESCENDING)],
        name="idx_account_report_date",
    )


async def _ensure_backtest_runs(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Queryable index of every strangle backtest / sweep / walk-forward run."""
    try:
        await db.create_collection("backtest_runs")
        log.info("mongo_collection_created", collection="backtest_runs")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="backtest_runs")

    col = db["backtest_runs"]
    await col.create_index([("run_id", ASCENDING)], unique=True, name="uq_run_id")
    await col.create_index([("kind", ASCENDING), ("created_at", DESCENDING)], name="idx_kind_created")
    await col.create_index([("metrics.profit_factor", DESCENDING)], name="idx_pf")
    await col.create_index([("metrics.net", DESCENDING)], name="idx_net")
    await col.create_index([("metrics.max_dd", ASCENDING)], name="idx_maxdd")
    await col.create_index([("metrics.sharpe", DESCENDING)], sparse=True, name="idx_sharpe")


async def _ensure_backtest_days(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Per-day P&L + equity series for each run — enough to reconstruct equity/drawdown curves."""
    try:
        await db.create_collection("backtest_days")
        log.info("mongo_collection_created", collection="backtest_days")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="backtest_days")

    col = db["backtest_days"]
    await col.create_index([("run_id", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_run_date")
    await col.create_index([("run_id", ASCENDING)], name="idx_run_id")


async def _ensure_backtest_folds(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Walk-forward fold records: IS window, OOS window, selected config, IS + OOS metrics."""
    try:
        await db.create_collection("backtest_folds")
        log.info("mongo_collection_created", collection="backtest_folds")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="backtest_folds")

    col = db["backtest_folds"]
    await col.create_index(
        [("run_id", ASCENDING), ("fold_index", ASCENDING)], unique=True, name="uq_run_fold")
    await col.create_index([("run_id", ASCENDING)], name="idx_run_id")


async def _ensure_backtest_trades(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Per-day fill buckets (one document per run+date holding all fills for that day)."""
    try:
        await db.create_collection("backtest_trades")
        log.info("mongo_collection_created", collection="backtest_trades")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="backtest_trades")

    col = db["backtest_trades"]
    await col.create_index([("run_id", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_run_date")
    await col.create_index([("run_id", ASCENDING)], name="idx_run_id")


async def _ensure_backtest_sweeps(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Sweep leaderboards: one doc per sweep_id with ranked combos + best_param."""
    try:
        await db.create_collection("backtest_sweeps")
        log.info("mongo_collection_created", collection="backtest_sweeps")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="backtest_sweeps")

    col = db["backtest_sweeps"]
    await col.create_index([("sweep_id", ASCENDING)], unique=True, name="uq_sweep_id")
    await col.create_index([("created_at", DESCENDING)], name="idx_created")


async def _ensure_backtest_decisions(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Strategy-agnostic why-entry/why-exit decision events, one doc per event."""
    try:
        await db.create_collection("backtest_decisions")
        log.info("mongo_collection_created", collection="backtest_decisions")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="backtest_decisions")

    col = db["backtest_decisions"]
    await col.create_index(
        [("run_id", ASCENDING), ("ts_ist", ASCENDING), ("event", ASCENDING)],
        unique=True, name="uq_run_ts_event",
    )
    await col.create_index([("run_id", ASCENDING), ("date", ASCENDING)], name="idx_run_date")


async def _ensure_backtest_promotions(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Audit log of PASS-gated promotions: one evidence doc per promoted run."""
    try:
        await db.create_collection("backtest_promotions")
        log.info("mongo_collection_created", collection="backtest_promotions")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="backtest_promotions")

    col = db["backtest_promotions"]
    await col.create_index([("run_id", ASCENDING)], unique=True, name="uq_run_id")
    await col.create_index([("promoted_at", DESCENDING)], name="idx_promoted_at")


def get_broker_snapshots_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["broker_snapshots"]


def get_bars_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["market_bars"]


def get_expired_option_bars_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["expired_option_bars"]


def get_option_bars_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["option_bars"]


def get_chains_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["option_chains"]


def get_positional_snapshots_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["positional_eod_snapshots"]


def get_events_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["events"]


def get_oi_snapshots_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["oi_snapshots"]


def get_backtest_runs_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["backtest_runs"]


def get_backtest_days_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["backtest_days"]


def get_backtest_folds_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["backtest_folds"]


def get_backtest_trades_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["backtest_trades"]


def get_backtest_sweeps_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["backtest_sweeps"]


def get_backtest_decisions_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["backtest_decisions"]


def get_backtest_promotions_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["backtest_promotions"]


def get_index_levels_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["index_levels"]


def get_expiry_calendar_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["expiry_calendar"]


async def _ensure_events(db: AsyncIOMotorDatabase, ttl_days: int) -> None:  # type: ignore[type-arg]
    """Alerts/decision events written by ``EventService``/``EventStore`` (field ``security_id``)
    and, since `strangle-observability-gaps`, the strangle strategy's leg-open/leg-close events
    via ``EventWriter`` (field ``sid``, plus ``strategy_id`` — the two writers do not share a
    security-id field name). Regular (not time-series) collection — matches ``EventStore``'s
    existing ``insert_one``/``find`` usage, which time-series collections don't support
    identically. Indexes only cover fields both writers set (``event_type``, ``ts``); a query
    needing the leg identifier must filter client-side on ``sid`` vs ``security_id`` until the
    two event shapes are unified.
    """
    try:
        await db.create_collection("events")
        log.info("mongo_collection_created", collection="events")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="events")

    col = db["events"]
    await col.create_index(
        [("ts", ASCENDING)],
        expireAfterSeconds=ttl_days * 86400,
        name="ttl_ts",
    )
    await col.create_index(
        [("event_type", ASCENDING), ("ts", DESCENDING)],
        name="idx_type_ts",
    )


async def _ensure_index_levels(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Create index_levels as a regular (non-time-series) collection + compound indexes.

    Regular collection (not time-series) is required because we upsert by unique key;
    MongoDB TS collections reject upsert operations.
    """
    col: AsyncIOMotorCollection = db["index_levels"]  # type: ignore[type-arg]
    # Unique index: (security_id, period, session_date) — the natural upsert key
    await col.create_index(
        [("security_id", ASCENDING), ("period", ASCENDING), ("session_date", ASCENDING)],
        unique=True,
        name="idx_levels_unique_key",
    )
    # Secondary: (underlying, period, session_date) for name-based lookups
    await col.create_index(
        [("underlying", ASCENDING), ("period", ASCENDING), ("session_date", ASCENDING)],
        name="idx_levels_underlying_period_date",
    )
    log.debug("mongo_indexes_ensured", collection="index_levels")


async def _ensure_expiry_calendar(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Persistent, DB-backed store of confirmed real expiry dates per underlying/flag.

    Replaces the static ``data/expiry/*.json`` cache as the source `pdp.options.gap_backfill`
    resolves target expiries from — that JSON cache carries the same coverage gaps as
    `option_bars` itself (it was built from the same incomplete ingestion), so any tool that
    resolves an expiry from it can never target a genuinely-missing expiry. Populated by
    `scripts/seed_expiry_calendar.py`, either migrated from the JSON cache or added one date at
    a time as gaps are confirmed against a real historical NSE calendar (see
    `option-bars-expiry-gap-backfill`).
    """
    try:
        await db.create_collection("expiry_calendar")
        log.info("mongo_collection_created", collection="expiry_calendar")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="expiry_calendar")

    col = db["expiry_calendar"]
    await col.create_index(
        [("underlying", ASCENDING), ("flag", ASCENDING), ("expiry_date", ASCENDING)],
        unique=True,
        name="uq_underlying_flag_expiry",
    )
