"""Tests for scripts/oneoff/rebuild_market_bars.py (bar-session-anchoring, task group 4).

Uses an in-memory async stub for the market_bars collection (same pattern as
tests/test_warehouse_coverage.py's `_FakeCollection`) instead of a real MongoDB, so these
run offline and never touch production data.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "oneoff"))

from rebuild_market_bars import rebuild_one, rollup_bars

from pdp.market.bars import BarAggregator
from pdp.market.models import Tick


class _AsyncCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def sort(self, *_args, **_kwargs):
        return self

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for row in self._rows:
            yield row


class _FakeBarsCollection:
    """Stub for market_bars: find/count_documents/delete_many/insert_many, in-memory."""

    def __init__(self, docs: list[dict] | None = None) -> None:
        self._docs = list(docs or [])

    def _match(self, query: dict, doc: dict) -> bool:
        if doc["metadata"]["security_id"] != query["metadata.security_id"]:
            return False
        if doc["metadata"]["timeframe"] != query["metadata.timeframe"]:
            return False
        ts_range = query["ts"]
        return ts_range["$gte"] <= doc["ts"] < ts_range["$lt"]

    def find(self, query: dict):
        return _AsyncCursor([d for d in self._docs if self._match(query, d)])

    async def count_documents(self, query: dict) -> int:
        return sum(1 for d in self._docs if self._match(query, d))

    async def delete_many(self, query: dict) -> None:
        self._docs = [d for d in self._docs if not self._match(query, d)]

    async def insert_many(self, docs: list[dict], ordered: bool = True) -> None:
        self._docs.extend(docs)


def _1m_doc(sid: str, iso: str, o: float, h: float, low: float, c: float, vol: int = 10) -> dict:
    return {
        "ts": datetime.fromisoformat(iso).replace(tzinfo=UTC),
        "metadata": {"security_id": sid, "timeframe": "1m"},
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": vol,
        "oi": 0,
    }


# Six consecutive 1m bars starting at the session open (09:15 IST = 03:45 UTC), so the
# first 5 fall in the first 30m bucket (09:15-09:45) and the 6th opens the next one.
_SESSION_1M_BARS = [
    _1m_doc("13", "2026-06-29T03:45:00", 100, 102, 99, 101),
    _1m_doc("13", "2026-06-29T03:46:00", 101, 103, 100, 102),
    _1m_doc("13", "2026-06-29T03:47:00", 102, 105, 101, 104),
    _1m_doc("13", "2026-06-29T03:48:00", 104, 104, 98, 99),
    _1m_doc("13", "2026-06-29T03:49:00", 99, 100, 97, 98),
    _1m_doc("13", "2026-06-29T04:15:00", 98, 99, 96, 97),
]


class TestRollupBars:
    def test_groups_by_session_anchored_boundary(self) -> None:
        out = rollup_bars(_SESSION_1M_BARS, 30, "30m")
        assert len(out) == 2
        first, second = out
        assert first["ts"] == datetime(2026, 6, 29, 3, 45, tzinfo=UTC)
        assert second["ts"] == datetime(2026, 6, 29, 4, 15, tzinfo=UTC)

    def test_ohlcv_aggregation_is_correct(self) -> None:
        out = rollup_bars(_SESSION_1M_BARS, 30, "30m")
        first = out[0]
        assert first["open"] == 100  # first 1m bar's open
        assert first["high"] == 105  # max high across the group
        assert first["low"] == 97  # min low across the group
        assert first["close"] == 98  # last 1m bar's close
        assert first["volume"] == 50  # sum of the 5 grouped volumes


class TestRebuildIdempotence:
    async def test_running_twice_yields_identical_document_set(self) -> None:
        col = _FakeBarsCollection(docs=list(_SESSION_1M_BARS))
        start = datetime(2026, 6, 29, tzinfo=UTC)
        end = start + timedelta(days=1)

        await rebuild_one(col, "13", "30m", start, end, dry_run=False)
        first_run = sorted(
            (d for d in col._docs if d["metadata"]["timeframe"] == "30m"), key=lambda d: d["ts"]
        )

        await rebuild_one(col, "13", "30m", start, end, dry_run=False)
        second_run = sorted(
            (d for d in col._docs if d["metadata"]["timeframe"] == "30m"), key=lambda d: d["ts"]
        )

        assert first_run == second_run

    async def test_dry_run_makes_no_writes(self) -> None:
        col = _FakeBarsCollection(docs=list(_SESSION_1M_BARS))
        start = datetime(2026, 6, 29, tzinfo=UTC)
        end = start + timedelta(days=1)

        summary = await rebuild_one(col, "13", "30m", start, end, dry_run=True)

        assert summary["new_count"] == 2
        assert not any(d["metadata"]["timeframe"] == "30m" for d in col._docs)


class TestRebuildEquivalenceWithBarAggregator:
    async def test_matches_live_tick_replay_for_one_session(self) -> None:
        """The script's bar-level rollup must match BarAggregator's tick-level aggregation
        when the 1m bars themselves came from a proper tick stream (full fidelity)."""
        ticks = [
            ("2026-06-29T03:45:10", "24500"),
            ("2026-06-29T03:45:40", "24550"),
            ("2026-06-29T03:46:05", "24480"),
            ("2026-06-29T03:46:50", "24600"),
        ]
        agg = BarAggregator(timeframes=["1m", "30m"])
        closed: list = []
        for iso, ltp in ticks:
            closed.extend(
                agg.push(
                    Tick(
                        security_id="13",
                        exchange_segment="NSE_EQ",
                        ltp=Decimal(ltp),
                        ltt=datetime.fromisoformat(iso).replace(tzinfo=UTC),
                        volume=1,
                        oi=0,
                        ts_recv=0.0,
                    )
                )
            )
        closed.extend(agg.flush_session())

        closed_1m = [b for b in closed if b.timeframe == "1m"]
        live_30m = next(b for b in closed if b.timeframe == "30m")

        one_min_docs = [
            {
                "ts": b.bar_time,
                "metadata": {"security_id": b.security_id, "timeframe": "1m"},
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": b.volume,
                "oi": b.oi,
            }
            for b in closed_1m
        ]

        rolled_up = rollup_bars(one_min_docs, 30, "30m")

        assert live_30m is not None
        assert len(rolled_up) == 1
        assert rolled_up[0]["ts"] == live_30m.bar_time
        assert rolled_up[0]["open"] == float(live_30m.open)
        assert rolled_up[0]["high"] == float(live_30m.high)
        assert rolled_up[0]["low"] == float(live_30m.low)
        assert rolled_up[0]["close"] == float(live_30m.close)
        assert rolled_up[0]["volume"] == live_30m.volume
