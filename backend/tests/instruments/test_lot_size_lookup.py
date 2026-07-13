"""Unit tests for `lot_size_for_underlying` — the live-instruments-table lot-size lookup
that replaces the static YAML `lot_size` as the authoritative sizing source
(lot-size-live-reconciliation)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.strategy.strikes import lot_size_for_underlying


def _fake_session(scalar_result: int | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_result
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_returns_lot_size_for_a_resolvable_row():
    session = _fake_session(75)
    assert await lot_size_for_underlying(session, "NIFTY") == 75


@pytest.mark.asyncio
async def test_returns_none_when_no_matching_rows():
    session = _fake_session(None)
    assert await lot_size_for_underlying(session, "GHOST_INDEX") is None
