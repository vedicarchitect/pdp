from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://pdp:pdp@localhost:5432/pdp"
)
os.environ.setdefault(
    "DATABASE_SYNC_URL", "postgresql+psycopg://pdp:pdp@localhost:5432/pdp"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Full-lifespan tests (test_healthz.py, test_app_start_log.py) run the real
# FeedEngineGroup.start(), which opens a live Dhan WebSocket feed connection
# whenever both creds are present — force them off so tests never dial out,
# regardless of what's configured in backend/.env for local paper trading.
os.environ["DHAN_CLIENT_ID"] = ""
os.environ["DHAN_ACCESS_TOKEN"] = ""


@pytest.fixture(autouse=True)
def mock_mongo_lifespan():
    """Patch Mongo connect/init/disconnect for all tests that exercise the app lifespan.

    Tests that need fine-grained control (test_mongo.py) apply their own patches
    inside the test body which take precedence over this outer autouse patch.
    """
    mock_db = MagicMock()
    mock_db.command = AsyncMock(return_value={"ok": 1})
    mock_db.create_collection = AsyncMock()
    chains_col = MagicMock()
    chains_col.create_index = AsyncMock()
    mock_db.__getitem__ = MagicMock(return_value=chains_col)

    with (
        patch("pdp.main.mongo_connect", return_value=(MagicMock(), mock_db)),
        patch("pdp.main.init_collections", new=AsyncMock()),
        patch("pdp.main.mongo_disconnect"),
    ):
        yield mock_db
