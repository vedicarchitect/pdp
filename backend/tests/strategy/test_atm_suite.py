"""Tests for pdp.strategy.atm_suite — the on-demand NIFTY ATM CE/PE indicator suite.

Covers: resolving the ATM option degrades honestly (returns None, never guesses) when the
instruments table has no matching row; the row-builder rolls up 1m option_bars into matrix
timeframes and omits indicators that lack sufficient history rather than fabricating values;
Camarilla/period-levels are never present on ATM rows.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

from pdp.strategy.atm_suite import build_atm_option_row, resolve_nifty_atm_option


class _AsyncCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for row in self._rows:
            yield row


class _FakeOptionBarsCollection:
    """Stub for option_bars: find(security_id, timeframe="1m", ts>=since) -> sorted docs."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = sorted(docs, key=lambda d: d["ts"])

    def find(self, match: dict, sort=None):
        sid = match["security_id"]
        since = match["ts"]["$gte"]
        rows = [d for d in self._docs if d["security_id"] == sid and d["ts"] >= since]
        return _AsyncCursor(rows)


def _opt_bar(sid: str, day: date, hh: int, mm: int, close: float) -> dict:
    ts = datetime(day.year, day.month, day.day, hh, tzinfo=UTC) + timedelta(minutes=mm)
    return {
        "security_id": sid,
        "ts": ts,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1000,
        "oi": 500,
    }


async def test_resolve_nifty_atm_option_returns_none_without_expiry() -> None:
    """Degrade honestly: no expiry in the instruments table means no security_id is
    guessed — the caller must skip the row entirely."""
    with patch("pdp.strategy.atm_suite.nearest_expiry", new=AsyncMock(return_value=None)):
        result = await resolve_nifty_atm_option(session=object(), spot=24050.0, option_type="CE")
    assert result is None


async def test_resolve_nifty_atm_option_returns_none_without_instrument_row() -> None:
    with (
        patch("pdp.strategy.atm_suite.nearest_expiry", new=AsyncMock(return_value=date(2026, 7, 17))),
        patch("pdp.strategy.atm_suite.resolve_otm_option", new=AsyncMock(return_value=None)),
    ):
        result = await resolve_nifty_atm_option(session=object(), spot=24050.0, option_type="PE")
    assert result is None


async def test_resolve_nifty_atm_option_resolves_strike_and_security_id() -> None:
    fake_inst = type("Inst", (), {"security_id": "99999"})()
    with (
        patch("pdp.strategy.atm_suite.nearest_expiry", new=AsyncMock(return_value=date(2026, 7, 17))),
        patch("pdp.strategy.atm_suite.resolve_otm_option", new=AsyncMock(return_value=fake_inst)),
    ):
        result = await resolve_nifty_atm_option(session=object(), spot=24050.0, option_type="CE")
    assert result == ("99999", 24050.0, date(2026, 7, 17))


async def test_build_atm_option_row_populates_5m_cell_from_rollup() -> None:
    day = date(2026, 7, 14)
    sid = "99999"
    docs = [
        _opt_bar(sid, day, 3, 45 + i, close=200.0 + i)
        for i in range(30)  # 30 consecutive 1m bars from session open
    ]
    col = _FakeOptionBarsCollection(docs)

    row = await build_atm_option_row(
        col, sid, strike=24050.0, expiry=date(2026, 7, 17), opt_type="CE",
        matrix_tfs=["5m", "15m", "1D"], since=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert row["label"] == "NIFTY 24050 CE"
    assert row["security_id"] == sid
    assert "5m" in row["tf"]
    assert row["tf"]["5m"]  # non-empty — some 5m bars rolled up
    # ema200 needs far more history than 30x 1m bars can produce even at 5m granularity
    assert "ema200" not in row["tf"]["5m"] or row["tf"]["5m"].get("ema200") is None


async def test_build_atm_option_row_omits_1d_and_unrecognized_tfs() -> None:
    """1D isn't derived from 1m here (out of scope) — its cell is present but empty,
    never a guessed value."""
    sid = "99999"
    col = _FakeOptionBarsCollection([_opt_bar(sid, date(2026, 7, 14), 3, 45, close=200.0)])

    row = await build_atm_option_row(
        col, sid, strike=24050.0, expiry=date(2026, 7, 17), opt_type="PE",
        matrix_tfs=["5m", "1D"], since=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert row["tf"]["1D"] == {}


async def test_build_atm_option_row_no_bars_returns_empty_cells_not_error() -> None:
    col = _FakeOptionBarsCollection([])

    row = await build_atm_option_row(
        col, "99999", strike=24050.0, expiry=date(2026, 7, 17), opt_type="CE",
        matrix_tfs=["5m", "15m"], since=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert row["tf"]["5m"] == {}
    assert row["tf"]["15m"] == {}


async def test_build_atm_option_row_never_includes_camarilla_or_period_levels() -> None:
    """ATM rows are index-only-concept-free: Camarilla/PDH-PWH-PMH must never appear."""
    day = date(2026, 7, 14)
    sid = "99999"
    docs = [_opt_bar(sid, day, 3, 45 + i, close=200.0 + i) for i in range(15)]
    col = _FakeOptionBarsCollection(docs)

    row = await build_atm_option_row(
        col, sid, strike=24050.0, expiry=date(2026, 7, 17), opt_type="CE",
        matrix_tfs=["5m"], since=datetime(2026, 7, 1, tzinfo=UTC),
    )

    cell = row["tf"]["5m"]
    assert "camarilla_daily" not in cell
    assert "camarilla_weekly" not in cell
    assert "camarilla_monthly" not in cell
    assert "period" not in cell
