import asyncio
import os
import structlog
from motor.motor_asyncio import AsyncIOMotorClient

log = structlog.get_logger()

async def backfill():
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.environ.get("MONGO_DB_NAME", "pdp_warehouse")
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    log.info("Starting underlying backfill...")

    runs = db["backtest_runs"]
    sweeps = db["backtest_sweeps"]

    run_updates = 0
    async for doc in runs.find({"underlying": {"$exists": False}}):
        config = doc.get("config") or {}
        underlying = (config.get("underlying") or "").upper()
        if underlying:
            await runs.update_one({"_id": doc["_id"]}, {"$set": {"underlying": underlying}})
            run_updates += 1

    sweep_updates = 0
    async for doc in sweeps.find({"underlying": {"$exists": False}}):
        # Sweeps use base_config or first combo's config
        base_config = doc.get("base_config") or {}
        if not base_config and doc.get("combos"):
            base_config = doc["combos"][0].get("params") or {}
        underlying = (base_config.get("underlying") or "").upper()
        if underlying:
            await sweeps.update_one({"_id": doc["_id"]}, {"$set": {"underlying": underlying}})
            sweep_updates += 1

    log.info("backfill_complete", runs_updated=run_updates, sweeps_updated=sweep_updates)

if __name__ == "__main__":
    asyncio.run(backfill())
