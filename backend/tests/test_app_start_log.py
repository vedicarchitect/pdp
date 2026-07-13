"""dev-reload-scoping: an unexplained restart must be attributable from logs alone.

`app_start` carries `started_at` + whether `--reload` was on `sys.argv`, so a mid-session
restart doesn't have to be inferred by polling `/healthz`. See
openspec/changes/dev-reload-scoping/proposal.md.
"""
from __future__ import annotations

import structlog.testing
from httpx import ASGITransport, AsyncClient

import pdp.main as main_module
from pdp.main import create_app


async def test_app_start_logged_once_with_started_at_and_reload_flag() -> None:
    # `pdp.main.log` is a module-level structlog proxy shared across the whole test
    # session. `cache_logger_on_first_use=True` (pdp/logging.py) makes a proxy
    # monkeypatch its own `bind` on its very first call, permanently caching whatever
    # processor chain was active at that moment. If an earlier test already triggered
    # the app lifespan (and thus this same `log.info("app_start", ...)` call) outside of
    # `capture_logs()`, that caching already happened and this test's `capture_logs()`
    # would never see the event — reproduced as `assert 0 == 1` when run in the full
    # suite while passing standalone. Clear the cached bind so it re-resolves against
    # the processor chain active now.
    main_module.log.__dict__.pop("bind", None)

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
