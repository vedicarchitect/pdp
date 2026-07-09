"""Offline tests for the live options warehouser (no Dhan creds, no MongoDB required).

Proves that:
1. ContractMeta round-trips through OptionBarWriter correctly: a BarClosed for a known
   security_id produces the right build_option_bar_doc fields in the upsert op.
2. A BarClosed for the configured index sid goes to the spot (market_bars) buffer.
3. An unknown security_id (not in the band) is silently dropped.
4. ``upsert_option_bars_async`` is called with the correct doc shape (via a stub collection).
5. When two underlyings are configured, ticks for each sid route to the correct writer.
6. An unsupported underlying name raises ValueError at WarehouseService construction time.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from pdp.market.bars import BarClosed
from pdp.options.warehouse import KEY_FIELDS
from pdp.warehouse.writer import ContractMeta, OptionBarWriter

# ── Stub collection ──────────────────────────────────────────────────────────


class _StubBulkResult:
    def __init__(self, upserted: int) -> None:
        self.upserted_count = upserted


class _StubCollection:
    """Async stub that captures bulk_write and insert_many calls."""

    def __init__(self) -> None:
        self.bulk_write_calls: list[list[Any]] = []
        self.insert_many_calls: list[list[Any]] = []

    async def bulk_write(self, ops: list[Any], ordered: bool = True) -> _StubBulkResult:
        self.bulk_write_calls.append(list(ops))
        return _StubBulkResult(upserted=len(ops))

    async def insert_many(self, docs: list[Any], ordered: bool = True) -> None:
        self.insert_many_calls.append(list(docs))


# ── Helpers ───────────────────────────────────────────────────────────────────

_EXPIRY = date(2026, 6, 17)
_STRIKE = 24800.0
_SID = "99001"
_NIFTY_SPOT_SID = "13"
_BANKNIFTY_SPOT_SID = "25"
_BAR_TIME = datetime(2026, 6, 13, 4, 15, tzinfo=UTC)  # 09:45 IST in UTC

_NIFTY_CFG = {"sid": _NIFTY_SPOT_SID, "step": 50, "underlying": "NIFTY"}
_BANKNIFTY_CFG = {"sid": _BANKNIFTY_SPOT_SID, "step": 100, "underlying": "BANKNIFTY"}


def _make_meta(underlying: str = "NIFTY") -> ContractMeta:
    return ContractMeta(
        underlying=underlying,
        expiry_date=_EXPIRY,
        strike=_STRIKE,
        option_type="CE",
        expiry_flag="WEEK",
        trading_symbol=f"{underlying}-Jun2026-24800-CE",
        security_id=_SID,
        strike_label="ATM",
    )


def _make_bar(security_id: str = _SID) -> BarClosed:
    return BarClosed(
        security_id=security_id,
        timeframe="1m",
        bar_time=_BAR_TIME,
        open=Decimal("150.0"),
        high=Decimal("155.0"),
        low=Decimal("148.0"),
        close=Decimal("153.0"),
        volume=500,
        oi=20000,
    )


def _run(coro):
    return asyncio.run(coro)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_option_bar_enqueued_and_flushed_with_correct_fields() -> None:
    """A BarClosed for a known option sid produces a correctly shaped upsert op."""
    opt_col = _StubCollection()
    mkt_col = _StubCollection()

    writer = OptionBarWriter(opt_col, mkt_col, underlying_cfg=_NIFTY_CFG)  # type: ignore[arg-type]
    writer.set_band({_SID: _make_meta()})

    bar = _make_bar(_SID)
    writer.enqueue(bar)

    # Manually trigger flush (without starting the background task)
    _run(writer._flush_options())

    assert len(opt_col.bulk_write_calls) == 1
    ops = opt_col.bulk_write_calls[0]
    assert len(ops) == 1

    # The UpdateOne filter must contain all KEY_FIELDS
    op = ops[0]
    filt = op._filter  # pymongo UpdateOne stores filter as _filter
    for k in KEY_FIELDS:
        assert k in filt, f"missing key field: {k}"

    # Check values
    assert filt["underlying"] == "NIFTY"
    assert filt["strike"] == _STRIKE
    assert filt["option_type"] == "CE"
    assert filt["timeframe"] == "1m"
    assert filt["expiry_date"].date() == _EXPIRY

    # The $setOnInsert payload must carry source=live and correct ohlcv
    payload = op._doc["$setOnInsert"]
    assert payload["source"] == "live"
    assert payload["trading_symbol"] == "NIFTY-Jun2026-24800-CE"
    assert payload["expiry_flag"] == "WEEK"
    assert payload["open"] == 150.0
    assert payload["close"] == 153.0
    assert payload["volume"] == 500
    assert payload["oi"] == 20000

    # Spot buffer must be empty
    assert len(mkt_col.insert_many_calls) == 0


def test_spot_bar_goes_to_market_bars() -> None:
    """A BarClosed for the index sid is routed to the market_bars buffer."""
    opt_col = _StubCollection()
    mkt_col = _StubCollection()

    writer = OptionBarWriter(opt_col, mkt_col, underlying_cfg=_NIFTY_CFG)  # type: ignore[arg-type]
    writer.set_band({})  # no option band needed for spot test

    bar = _make_bar(_NIFTY_SPOT_SID)  # sid "13"
    writer.enqueue(bar)

    _run(writer._flush_spot())

    assert len(mkt_col.insert_many_calls) == 1
    docs = mkt_col.insert_many_calls[0]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["metadata"]["security_id"] == _NIFTY_SPOT_SID
    assert doc["metadata"]["timeframe"] == "1m"
    assert doc["close"] == 153.0

    # Option buffer must be untouched
    assert len(opt_col.bulk_write_calls) == 0


def test_unknown_security_id_silently_dropped() -> None:
    """A BarClosed for an sid not in the band map produces no upserts."""
    opt_col = _StubCollection()
    mkt_col = _StubCollection()

    writer = OptionBarWriter(opt_col, mkt_col, underlying_cfg=_NIFTY_CFG)  # type: ignore[arg-type]
    writer.set_band({})  # empty band

    bar = _make_bar("99999")  # not in band, not the index sid
    writer.enqueue(bar)

    _run(writer._flush_all())

    assert len(opt_col.bulk_write_calls) == 0
    assert len(mkt_col.insert_many_calls) == 0


def test_band_update_takes_effect_immediately() -> None:
    """set_band replacement is reflected in the next enqueue call."""
    opt_col = _StubCollection()
    mkt_col = _StubCollection()

    writer = OptionBarWriter(opt_col, mkt_col, underlying_cfg=_NIFTY_CFG)  # type: ignore[arg-type]
    writer.set_band({})  # empty initially

    bar = _make_bar(_SID)
    writer.enqueue(bar)
    _run(writer._flush_options())
    assert len(opt_col.bulk_write_calls) == 0  # dropped — not in band yet

    # Now update the band
    writer.set_band({_SID: _make_meta()})
    writer.enqueue(bar)
    _run(writer._flush_options())
    assert len(opt_col.bulk_write_calls) == 1  # now captured


def test_contract_meta_fields_match_bar_doc_identity() -> None:
    """The doc built from ContractMeta contains the exact expiry_date + strike used as the key."""
    from pdp.options.warehouse import build_option_bar_doc

    meta = _make_meta()
    doc = build_option_bar_doc(
        underlying=meta.underlying,
        expiry_date=meta.expiry_date,
        strike=meta.strike,
        option_type=meta.option_type,
        timeframe="1m",
        ts=_BAR_TIME,
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
        volume=100,
        oi=5000,
        iv=0.0,
        expiry_flag=meta.expiry_flag,
        trading_symbol=meta.trading_symbol,
        security_id=meta.security_id,
        strike_label=meta.strike_label,
        source="live",
    )

    assert doc["underlying"] == "NIFTY"
    assert doc["strike"] == _STRIKE
    assert doc["option_type"] == "CE"
    assert doc["source"] == "live"
    assert doc["expiry_date"].year == _EXPIRY.year
    assert doc["expiry_date"].month == _EXPIRY.month
    assert doc["expiry_date"].day == _EXPIRY.day


def test_nifty_expiry_calendar_resolve_for_band() -> None:
    """NiftyExpiryCalendar.resolve_expiry returns correct code-1 and code-2 expiries."""
    from pdp.instruments.expiry_calendar import NiftyExpiryCalendar

    weekly = [
        date(2026, 6, 17),
        date(2026, 6, 24),
        date(2026, 7, 1),
    ]
    cal = NiftyExpiryCalendar({"WEEK": weekly})

    today = date(2026, 6, 13)
    assert cal.resolve_expiry(today, "WEEK", 1) == date(2026, 6, 17)
    assert cal.resolve_expiry(today, "WEEK", 2) == date(2026, 6, 24)


# ── Multi-underlying tests (tasks 5.2 and 5.3) ───────────────────────────────


def test_banknifty_option_bar_routes_to_banknifty_writer() -> None:
    """When BANKNIFTY writer is configured, option bars are tagged with underlying='BANKNIFTY'."""
    bnf_option_sid = "88001"
    opt_col = _StubCollection()
    mkt_col = _StubCollection()

    writer = OptionBarWriter(opt_col, mkt_col, underlying_cfg=_BANKNIFTY_CFG)  # type: ignore[arg-type]
    meta = ContractMeta(
        underlying="BANKNIFTY",
        expiry_date=_EXPIRY,
        strike=52000.0,
        option_type="CE",
        expiry_flag="WEEK",
        trading_symbol="BANKNIFTY-Jun2026-52000-CE",
        security_id=bnf_option_sid,
        strike_label="ATM",
    )
    writer.set_band({bnf_option_sid: meta})

    bar = _make_bar(bnf_option_sid)
    writer.enqueue(bar)
    _run(writer._flush_options())

    assert len(opt_col.bulk_write_calls) == 1
    op = opt_col.bulk_write_calls[0][0]
    assert op._filter["underlying"] == "BANKNIFTY"

    # A NIFTY writer with a different underlying_cfg must NOT receive this bar.
    nifty_opt_col = _StubCollection()
    nifty_mkt_col = _StubCollection()
    nifty_writer = OptionBarWriter(nifty_opt_col, nifty_mkt_col, underlying_cfg=_NIFTY_CFG)  # type: ignore[arg-type]
    nifty_writer.set_band({})  # NIFTY writer has no BANKNIFTY options in band

    nifty_writer.enqueue(bar)
    _run(nifty_writer._flush_options())
    assert len(nifty_opt_col.bulk_write_calls) == 0  # not cross-contaminated


def _make_service(tmp_path, underlyings: list[str], *, existing_paths: set[str]):
    """Build a WarehouseService offline (no Dhan/Mongo I/O touched by __init__)."""
    import pdp.warehouse.service as service_mod

    path_settings = {
        "NIFTY": "EXPIRY_CACHE_PATH",
        "BANKNIFTY": "BANKNIFTY_EXPIRY_CACHE_PATH",
        "SENSEX": "SENSEX_EXPIRY_CACHE_PATH",
    }
    fake_settings = MagicMock()
    fake_settings.WAREHOUSE_UNDERLYINGS = underlyings
    fake_settings.DHAN_CLIENT_ID = "x"
    fake_settings.DHAN_ACCESS_TOKEN = "x"
    fake_settings.WAREHOUSE_GAP_LOOKBACK_DAYS = 30
    fake_settings.WAREHOUSE_STRIKE_BAND = 10

    for name, attr in path_settings.items():
        p = tmp_path / f"{name.lower()}_expiries.json"
        if name in existing_paths:
            p.write_text("{}")
        setattr(fake_settings, attr, str(p))

    fake_mongo_db = MagicMock()
    fake_mongo_db.__getitem__ = MagicMock(return_value=MagicMock())
    fake_session_maker = MagicMock()

    return service_mod.WarehouseService(
        settings=fake_settings, mongo_db=fake_mongo_db, session_maker=fake_session_maker
    )


def test_run_gap_backfill_heals_every_underlying_with_expiry_cache(tmp_path, monkeypatch) -> None:
    """5.1/5.2: every configured underlying with a present expiry cache is backfilled; only a
    missing cache is skipped (with a warning naming the file), not a non-NIFTY name."""
    import pdp.options.gap_backfill as gap_backfill_mod

    svc = _make_service(tmp_path, ["NIFTY", "BANKNIFTY", "SENSEX"], existing_paths={"NIFTY", "BANKNIFTY"})

    calls: list[str] = []

    def _fake_run_gap_backfill(*, underlying, **_kwargs):
        calls.append(underlying)
        return {"scanned": 0, "gaps": 0, "days_filled": 0, "total_inserted": 0, "gap_days": []}

    monkeypatch.setattr(gap_backfill_mod, "run_gap_backfill", _fake_run_gap_backfill)

    asyncio.run(svc._run_gap_backfill())

    # NIFTY + BANKNIFTY have caches -> healed. SENSEX's cache is missing -> skipped, not healed.
    assert set(calls) == {"NIFTY", "BANKNIFTY"}


def test_unsupported_underlying_raises_value_error_at_startup() -> None:
    """WarehouseService raises ValueError for unrecognised underlyings before any I/O."""
    from pdp.warehouse.service import WarehouseService

    fake_settings = MagicMock()
    fake_settings.WAREHOUSE_UNDERLYINGS = ["NIFTY", "MIDCAP"]
    fake_settings.DHAN_CLIENT_ID = "x"
    fake_settings.DHAN_ACCESS_TOKEN = "x"

    fake_mongo_db = MagicMock()
    # Stub the collection getters so __init__ doesn't blow up before the validation.
    fake_mongo_db.__getitem__ = MagicMock(return_value=MagicMock())
    fake_session_maker = MagicMock()

    with pytest.raises(ValueError, match="MIDCAP"):
        WarehouseService(
            settings=fake_settings,
            mongo_db=fake_mongo_db,
            session_maker=fake_session_maker,
        )
