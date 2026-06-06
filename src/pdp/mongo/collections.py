from __future__ import annotations

import structlog
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING
from pymongo.errors import CollectionInvalid

from pdp.settings import Settings

log = structlog.get_logger()


async def init_collections(db: AsyncIOMotorDatabase, settings: Settings) -> None:  # type: ignore[type-arg]
    await _ensure_market_bars(db)
    await _ensure_option_chains(db, settings.MONGO_CHAIN_TTL_DAYS)


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


async def _ensure_option_chains(db: AsyncIOMotorDatabase, ttl_days: int) -> None:  # type: ignore[type-arg]
    try:
        await db.create_collection("option_chains")
        log.info("mongo_collection_created", collection="option_chains")
    except CollectionInvalid:
        log.debug("mongo_collection_exists", collection="option_chains")

    # create_index is idempotent when name+spec match. Changing MONGO_CHAIN_TTL_DAYS on
    # an existing deployment has no effect until the old index is dropped manually:
    #   mongosh pdp --eval 'db.option_chains.dropIndex("ttl_captured_at")'
    await db["option_chains"].create_index(
        [("captured_at", ASCENDING)],
        expireAfterSeconds=ttl_days * 86400,
        name="ttl_captured_at",
    )


def get_bars_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["market_bars"]


def get_chains_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:  # type: ignore[type-arg]
    return db["option_chains"]
