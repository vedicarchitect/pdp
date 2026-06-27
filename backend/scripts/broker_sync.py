"""CLI for broker account sync (chunk 2: broker-account-sync).

Daily sync:   uv run python scripts/broker_sync.py [--date YYYY-MM-DD]
Backfill:     uv run python scripts/broker_sync.py --from YYYY-MM-DD [--to YYYY-MM-DD]

Run via Taskfile from the repo root: `task broker:sync` / `task broker:backfill`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime

import structlog

from pdp.broker_sync.backfill import backfill_history
from pdp.broker_sync.client import BrokerAccountClient
from pdp.broker_sync.service import BrokerSyncService
from pdp.db.session import dispose_engine, get_session_maker
from pdp.mongo.client import connect, disconnect
from pdp.mongo.collections import _ensure_broker_snapshots
from pdp.settings import get_settings

log = structlog.get_logger()


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Dhan broker account sync / backfill")
    parser.add_argument("--date", help="Daily sync date (YYYY-MM-DD); default today")
    parser.add_argument("--from", dest="from_date", help="Backfill start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", help="Backfill end date; default today")
    args = parser.parse_args()

    settings = get_settings()
    client_obj = BrokerAccountClient(settings)
    if not client_obj.has_credentials:
        log.warning("broker_sync_cli_no_credentials")
        print("No Dhan credentials (DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN). Nothing to do.")
        return 0

    mongo_client, db = connect(settings)
    await _ensure_broker_snapshots(db)
    col = db["broker_snapshots"]
    session_maker = get_session_maker()

    try:
        if args.from_date:
            to_date = args.to_date or datetime.now(UTC).strftime("%Y-%m-%d")
            result = await backfill_history(client_obj, col, from_date=args.from_date, to_date=to_date)
        else:
            service = BrokerSyncService(session_maker, col, client_obj)
            result = await service.run_daily(args.date, trigger="manual")
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        disconnect(mongo_client)
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
