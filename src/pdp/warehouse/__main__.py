"""Entry point: ``python -m pdp.warehouse``.

Builds settings, motor client, async Postgres session maker, instantiates WarehouseService
(which loads per-underlying expiry calendars internally), and runs it.
Handles SIGINT/KeyboardInterrupt for graceful shutdown.
"""
from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from pdp.logging import configure_logging
from pdp.settings import get_settings
from pdp.warehouse.service import WarehouseService

log = structlog.get_logger()


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    if not settings.DHAN_CLIENT_ID or not settings.DHAN_ACCESS_TOKEN:
        log.error(
            "warehouse_no_dhan_creds",
            reason="DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN must be set",
        )
        sys.exit(1)

    # Motor (MongoDB) client
    from pdp.mongo.client import connect as mongo_connect
    from pdp.mongo.client import disconnect as mongo_disconnect
    from pdp.mongo.collections import init_collections

    mongo_client, mongo_db = mongo_connect(settings)
    await init_collections(mongo_db, settings)

    # Async Postgres session maker
    from pdp.db.session import get_session_maker

    session_maker = get_session_maker()

    service = WarehouseService(
        settings=settings,
        mongo_db=mongo_db,
        session_maker=session_maker,
    )

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        log.info("warehouse_signal_received", action="stopping")
        asyncio.ensure_future(service.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    try:
        await service.run()
    finally:
        mongo_disconnect(mongo_client)
        log.info("warehouse_shutdown_complete")


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
