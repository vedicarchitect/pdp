"""Ingest endpoint: valid batch accepted (source=ui), malformed → 422."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from pdp.observability import set_active_indexer
from pdp.observability.indexer import OpenSearchIndexer
from pdp.observability.ingest import router

# Minimal FastAPI app wiring just the ingest router.
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_indexer():
    idx = OpenSearchIndexer(client=MagicMock(), prefix="pdp", queue_max=100)
    set_active_indexer(idx)
    yield idx
    set_active_indexer(None)


def test_valid_batch_accepted(mock_indexer):
    payload = {
        "records": [
            {"level": "info", "event": "screen_loaded", "screen": "portfolio"},
            {"level": "error", "event": "crash", "screen": "chart"},
        ]
    }
    resp = client.post("/api/v1/logs/ingest", json=payload)
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 2
    assert mock_indexer._queue.qsize() == 2


def test_all_records_tagged_source_ui(mock_indexer):
    payload = {"records": [{"event": "btn_tap"}]}
    client.post("/api/v1/logs/ingest", json=payload)
    action = mock_indexer._queue.get_nowait()
    assert action["_source"]["source"] == "ui"


def test_empty_records_list_is_422():
    resp = client.post("/api/v1/logs/ingest", json={"records": []})
    assert resp.status_code == 422


def test_missing_event_field_is_422():
    resp = client.post("/api/v1/logs/ingest", json={"records": [{"level": "info"}]})
    assert resp.status_code == 422


def test_no_active_indexer_still_returns_accepted():
    set_active_indexer(None)
    payload = {"records": [{"event": "no_index"}]}
    resp = client.post("/api/v1/logs/ingest", json=payload)
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 1
