from __future__ import annotations

import asyncio

import click
import structlog
import uvicorn

from pdp.cli.backtest_commands import backtest
from pdp.cli.progress.main import progress
from pdp.cli.strategy_commands import strategy
from pdp.db.session import get_session_maker
from pdp.instruments.loader import download_dhan_master, parse_dhan_csv, refresh_instruments
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


@instruments.command("snapshot")
@click.option("--date", "date_str", default=None, help="Snapshot date (YYYY-MM-DD); defaults to today.")
@click.option("--dir", "masters_dir", default=None, help="Output dir; defaults to settings.MASTERS_DIR.")
def instruments_snapshot(date_str: str | None, masters_dir: str | None) -> None:
    """Download the Dhan scrip master and write today's filtered snapshot CSV.

    Filtered to settings.SNAPSHOT_UNDERLYINGS (default NIFTY/BANKNIFTY/SENSEX) so historical
    backtests can resolve expired-contract security_ids.
    """
    from datetime import date as _date
    from pathlib import Path

    from pdp.instruments.snapshots import create_snapshot, parse_underlyings

    log = structlog.get_logger()
    settings = get_settings()
    snap_date = _date.fromisoformat(date_str) if date_str else _date.today()
    out_dir = Path(masters_dir) if masters_dir else Path(settings.MASTERS_DIR)
    underlyings = parse_underlyings(settings.SNAPSHOT_UNDERLYINGS)

    async def _run() -> None:
        raw = await download_dhan_master(settings.DHAN_SCRIPMASTER_URL)
        rows = parse_dhan_csv(raw)
        path, kept = create_snapshot(rows, snap_date, out_dir, underlyings)
        log.info(
            "instruments_snapshot_done",
            date=snap_date.isoformat(),
            underlyings=list(underlyings),
            rows_seen=len(rows),
            rows_kept=kept,
            path=str(path),
        )

    asyncio.run(_run())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
