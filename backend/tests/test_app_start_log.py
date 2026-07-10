"""dev-reload-scoping: an unexplained restart must be attributable from logs alone.

`app_start` carries `started_at` + whether `--reload` was on `sys.argv`, so a mid-session
restart doesn't have to be inferred by polling `/healthz`. See
openspec/changes/dev-reload-scoping/proposal.md.
"""
from __future__ import annotations

import structlog.testing
from httpx import ASGITransport, AsyncClient

from pdp.main import create_app


async def test_app_start_logged_once_with_started_at_and_reload_flag() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    with structlog.testing.capture_logs() as captured:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.get("/healthz")

    app_start_events = [entry for entry in captured if entry.get("event") == "app_start"]
    assert len(app_start_events) == 1
    assert "started_at" in app_start_events[0]
    assert app_start_events[0]["reload"] is False
