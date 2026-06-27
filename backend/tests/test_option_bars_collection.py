"""Integration test for the option_bars dedup guarantee against a real MongoDB.

Skips automatically when a local MongoDB is not reachable (so CI without Mongo stays green).
Proves that the unique contract+ts index makes duplicate bars structurally impossible even when
two producers write the same (contract, ts).
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest

pymongo = pytest.importorskip("pymongo")
from pymongo import MongoClient  # noqa: E402

from pdp.options.warehouse import (  # noqa: E402
    KEY_FIELDS,
    build_option_bar_doc,
    upsert_option_bars_sync,
)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")


@pytest.fixture()
def coll():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except Exception:
        pytest.skip("local MongoDB not reachable")
    dbname = f"pdp_test_{uuid.uuid4().hex[:8]}"
    col = client[dbname]["option_bars"]
    # Mirror _ensure_option_bars: the unique contract+ts key.
    col.create_index([(k, 1) for k in KEY_FIELDS], unique=True, name="uq_contract_ts")
    try:
        yield col
    finally:
        client.drop_database(dbname)
        client.close()


def _doc(source: str, *, strike: float = 19150, close: float = 100.0):
    return build_option_bar_doc(
        underlying="NIFTY",
        expiry_date=date(2026, 6, 2),
        strike=strike,
        option_type="CE",
        timeframe="1m",
        ts=datetime(2026, 6, 1, 9, 15, tzinfo=timezone.utc),
        open=close, high=close, low=close, close=close,
        volume=1, oi=2, iv=10.0,
        expiry_flag="WEEK",
        trading_symbol="NIFTY-Jun2026-19150-CE",
        source=source,
    )


def test_same_contract_ts_two_producers_yields_one_doc(coll) -> None:
    n1 = upsert_option_bars_sync(coll, [_doc("abi", close=100.0)])
    n2 = upsert_option_bars_sync(coll, [_doc("live", close=999.0)])  # same key, different payload
    assert n1 == 1
    assert n2 == 0  # rejected by the unique index / no-op via $setOnInsert
    assert coll.count_documents({}) == 1
    doc = coll.find_one({})
    # First-write-wins: original bar retained.
    assert doc["source"] == "abi"
    assert doc["close"] == 100.0


def test_distinct_contracts_both_inserted(coll) -> None:
    inserted = upsert_option_bars_sync(coll, [_doc("abi", strike=19150), _doc("abi", strike=19200)])
    assert inserted == 2
    assert coll.count_documents({}) == 2
