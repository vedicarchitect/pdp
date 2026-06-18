"""Take a dated scrip-master snapshot for historical backtest lookups.

Fetches today's Dhan scrip master, filters to the configured underlyings,
and writes data/masters/YYYY-MM-DD.csv.

Usage:
    uv run python scripts/snapshot_instruments.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.instruments.loader import download_dhan_master, parse_dhan_csv  # noqa: E402
from pdp.instruments.snapshots import create_snapshot  # noqa: E402
from pdp.settings import get_settings  # noqa: E402


async def main() -> None:
    settings = get_settings()
    raw = await download_dhan_master(settings.DHAN_SCRIPMASTER_URL)
    rows = parse_dhan_csv(raw)
    today = datetime.now(UTC).date()
    path, n = create_snapshot(rows, today)
    print(f"Snapshot written: {path} ({n} instruments)")


if __name__ == "__main__":
    asyncio.run(main())
