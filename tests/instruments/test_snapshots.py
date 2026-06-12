"""Tests for daily filtered instrument snapshots."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pdp.instruments.snapshots import (
    DEFAULT_SNAPSHOT_UNDERLYINGS,
    create_snapshot,
    filter_for_underlyings,
    latest_snapshot_on_or_before,
    load_master_for_date,
    parse_underlyings,
    resolve_instrument,
    snapshot_path,
)


def _row(**kw):
    base = {
        "security_id": "1",
        "exchange_segment": "NSE_FNO",
        "trading_symbol": "X",
        "instrument_type": "OPTIDX",
        "underlying": None,
        "expiry": None,
        "strike": None,
        "option_type": None,
        "lot_size": 1,
        "tick_size": Decimal("0.05"),
        "isin": None,
    }
    base.update(kw)
    return base


def _master_rows():
    return [
        # Allowed: NIFTY weekly option.
        _row(security_id="42289", trading_symbol="NIFTY-23300-PE", underlying="NIFTY",
             expiry=date(2026, 6, 9), strike=Decimal("23300"), option_type="PE", lot_size=65),
        # Allowed: BANKNIFTY future.
        _row(security_id="500", trading_symbol="BANKNIFTY-FUT", underlying="BANKNIFTY",
             instrument_type="FUTIDX", expiry=date(2026, 6, 25), lot_size=15),
        # Allowed: SENSEX option (BSE).
        _row(security_id="900", exchange_segment="BSE_FNO", trading_symbol="SENSEX-80000-CE",
             underlying="SENSEX", expiry=date(2026, 6, 12), strike=Decimal("80000"),
             option_type="CE", lot_size=10),
        # Allowed: NIFTY index spot (IDX_I, no underlying — matched by symbol alias).
        _row(security_id="13", exchange_segment="IDX_I", trading_symbol="NIFTY 50",
             instrument_type="INDEX", lot_size=1),
        # Excluded: a different underlying.
        _row(security_id="111", trading_symbol="RELIANCE-2800-CE", underlying="RELIANCE",
             strike=Decimal("2800"), option_type="CE"),
        # Excluded: unrelated equity.
        _row(security_id="222", exchange_segment="NSE_EQ", trading_symbol="TCS",
             instrument_type="EQUITY", underlying=None),
    ]


def test_parse_underlyings_default_and_json():
    assert parse_underlyings('["NIFTY","BANKNIFTY","SENSEX"]') == ("NIFTY", "BANKNIFTY", "SENSEX")
    assert parse_underlyings(["nifty", "sensex"]) == ("NIFTY", "SENSEX")
    assert parse_underlyings("not-json") == DEFAULT_SNAPSHOT_UNDERLYINGS


def test_filter_keeps_only_allowed_underlyings_and_index():
    kept = filter_for_underlyings(_master_rows(), DEFAULT_SNAPSHOT_UNDERLYINGS)
    sids = {r["security_id"] for r in kept}
    assert sids == {"42289", "500", "900", "13"}  # 3 underlyings + NIFTY index
    assert "111" not in sids and "222" not in sids


def test_create_snapshot_writes_filtered_csv(tmp_path):
    path, kept = create_snapshot(_master_rows(), date(2026, 6, 10), tmp_path)
    assert path == snapshot_path(date(2026, 6, 10), tmp_path)
    assert path.exists()
    assert kept == 4

    rows = load_master_for_date(date(2026, 6, 10), tmp_path)
    assert {r["security_id"] for r in rows} == {"42289", "500", "900", "13"}
    # Values round-trip as strings.
    pe = next(r for r in rows if r["security_id"] == "42289")
    assert pe["underlying"] == "NIFTY" and pe["option_type"] == "PE"
    assert pe["expiry"] == "2026-06-09" and pe["strike"] == "23300"


def test_snapshot_is_idempotent(tmp_path):
    create_snapshot(_master_rows(), date(2026, 6, 10), tmp_path)
    n1 = len(load_master_for_date(date(2026, 6, 10), tmp_path))
    create_snapshot(_master_rows(), date(2026, 6, 10), tmp_path)  # re-run same day
    n2 = len(load_master_for_date(date(2026, 6, 10), tmp_path))
    assert n1 == n2 == 4
    assert list(tmp_path.glob("*.csv")) == [snapshot_path(date(2026, 6, 10), tmp_path)]


def test_load_picks_latest_on_or_before(tmp_path):
    create_snapshot(_master_rows(), date(2026, 6, 8), tmp_path)
    create_snapshot(_master_rows(), date(2026, 6, 10), tmp_path)

    assert latest_snapshot_on_or_before(date(2026, 6, 9), tmp_path) == date(2026, 6, 8)
    assert latest_snapshot_on_or_before(date(2026, 6, 10), tmp_path) == date(2026, 6, 10)
    assert latest_snapshot_on_or_before(date(2026, 6, 11), tmp_path) == date(2026, 6, 10)
    # A date with no exact snapshot uses the most recent prior one.
    rows = load_master_for_date(date(2026, 6, 9), tmp_path)
    assert len(rows) == 4


def test_load_raises_when_no_snapshot(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_master_for_date(date(2026, 6, 1), tmp_path)


def test_resolve_expired_contract_from_snapshot(tmp_path):
    create_snapshot(_master_rows(), date(2026, 6, 9), tmp_path)
    rows = load_master_for_date(date(2026, 6, 9), tmp_path)

    hit = resolve_instrument(
        rows, underlying="NIFTY", option_type="PE",
        strike=23300, expiry=date(2026, 6, 9),
    )
    assert hit is not None and hit["security_id"] == "42289"

    miss = resolve_instrument(rows, underlying="NIFTY", option_type="PE", strike=99999)
    assert miss is None
