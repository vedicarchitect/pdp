from __future__ import annotations

import asyncio

import click
import structlog
import uvicorn

from pdp.cli.backtest_commands import backtest
from pdp.cli.progress.main import progress
from pdp.cli.strategy_commands import strategy
from pdp.db.session import get_session_maker
from pdp.instruments.loader import refresh_instruments
from pdp.settings import get_settings


@click.group()
def cli() -> None:
    """PDP command-line interface."""


cli.add_command(progress)
cli.add_command(backtest)
cli.add_command(strategy)


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
@click.option("--reload", is_flag=True, default=False)
def serve(host: str, port: int, reload: bool) -> None:
    """Run the API server."""
    uvicorn.run("pdp.main:app", host=host, port=port, reload=reload)


@cli.group()
def instruments() -> None:
    """Instrument registry commands."""


@instruments.command("refresh")
def instruments_refresh() -> None:
    """Download Dhan scrip master and upsert into the instruments table."""
    log = structlog.get_logger()
    settings = get_settings()

    async def _run() -> None:
        async with get_session_maker()() as session:
            stats = await refresh_instruments(session, settings.DHAN_SCRIPMASTER_URL)
            log.info(
                "instruments_refresh_done",
                rows_seen=stats.rows_seen,
                rows_upserted=stats.rows_upserted,
            )

    asyncio.run(_run())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
