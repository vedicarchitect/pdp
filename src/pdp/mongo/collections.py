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
    await _ensure_option_chains(db, settings.MONGO_CHAIN_TTL_DAYS, settings.OPTIONS_CHAIN_TTL_DAYS)
    await _ensure_portfolio_snapshots(db)
    await _ensure_positional_eod_snapshots(db)


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


def get_bars_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["market_bars"]


def get_expired_option_bars_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["expired_option_bars"]


def get_chains_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["option_chains"]


def get_positional_snapshots_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["positional_eod_snapshots"]
