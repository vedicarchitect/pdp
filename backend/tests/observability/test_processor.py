"""Processor: record→doc shape, source derivation, observability self-skip."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pdp.observability import set_active_indexer
from pdp.observability.indexer import OpenSearchIndexer
from pdp.observability.processor import _to_log_doc, opensearch_sink, set_level_floor


@pytest.fixture(autouse=True)
def reset_indexer():
    """Ensure a fresh indexer state for each test."""
    idx = OpenSearchIndexer(client=MagicMock(), prefix="pdp", queue_max=100)
    set_active_indexer(idx)
    yield idx
    set_active_indexer(None)


def test_record_enqueued_and_returned(reset_indexer):
    ed = {"level": "info", "event": "hello", "logger": "pdp.market", "timestamp": "2026-06-28T10:00:00Z"}
    result = opensearch_sink(None, "info", ed)
    assert result is ed  # processor returns the same dict
    assert reset_indexer._queue.qsize() == 1
    action = reset_indexer._queue.get_nowait()
    assert action["_index"].startswith("pdp-logs-")
    assert action["_source"]["event"] == "hello"


def test_source_defaults_to_backend(reset_indexer):
    ed = {"level": "info", "event": "x", "timestamp": "2026-06-28T00:00:00Z"}
    opensearch_sink(None, "info", ed)
    doc = reset_indexer._queue.get_nowait()["_source"]
    assert doc["source"] == "backend"


def test_source_override_propagates(reset_indexer):
    ed = {"level": "info", "event": "x", "source": "strategy", "timestamp": "2026-06-28T00:00:00Z"}
    opensearch_sink(None, "info", ed)
    doc = reset_indexer._queue.get_nowait()["_source"]
    assert doc["source"] == "strategy"


def test_no_ship_flag_skips_enqueue_and_is_popped(reset_indexer):
    ed = {"level": "info", "event": "self", "_no_ship": True, "timestamp": "t"}
    result = opensearch_sink(None, "info", ed)
    assert "_no_ship" not in result
    assert reset_indexer._queue.qsize() == 0


def test_level_floor_suppresses_debug(reset_indexer):
    set_level_floor("info")
    ed = {"level": "debug", "event": "verbose", "timestamp": "2026-06-28T00:00:00Z"}
    opensearch_sink(None, "debug", ed)
    assert reset_indexer._queue.qsize() == 0


def test_extra_fields_go_to_context():
    ed = {
        "level": "info",
        "event": "ev",
        "timestamp": "2026-06-28T00:00:00Z",
        "custom_key": "custom_val",
        "another": 42,
    }
    doc = _to_log_doc(ed)
    assert doc["context"]["custom_key"] == "custom_val"
    assert doc["context"]["another"] == 42
    assert "custom_key" not in doc


def test_no_indexer_returns_event_dict():
    set_active_indexer(None)
    ed = {"level": "info", "event": "x", "timestamp": "t"}
    result = opensearch_sink(None, "info", ed)
    assert result is ed
