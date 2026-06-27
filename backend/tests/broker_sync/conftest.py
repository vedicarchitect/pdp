from __future__ import annotations

from typing import Any

import pytest

from pdp.db.session import dispose_engine


@pytest.fixture(autouse=True)
async def _fresh_engine() -> Any:
    """Dispose the global async engine around each test.

    ``get_engine()`` caches one engine/pool bound to the loop it was first used in;
    pytest-asyncio runs each test on its own loop, so without this the second DB-backed
    test reuses a pool bound to a closed loop ("Event loop is closed"). Disposing before
    and after each test makes every test build (and tear down) its own engine on its loop.
    """
    await dispose_engine()
    yield
    await dispose_engine()
