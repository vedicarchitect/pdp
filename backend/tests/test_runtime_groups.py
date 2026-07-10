"""Invariant: every runtime group with `required = True` actually starts.

A required group whose `start()` raises must abort app startup, not degrade silently.
The dead `pdp/orders/command_channel.py` import (`OrderRequest` didn't exist) killed
`WebGroup` and `FeedEngineGroup` on every boot for weeks before it was caught, because
nothing asserted these groups' post-start state — the API still came up "healthy".
See `memory/dead_command_channel_import.md`.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from pdp.main import create_app
from pdp.runtime.groups import GROUPS_BY_ROLE


def test_every_role_group_list_is_well_formed() -> None:
    """Every group class referenced by GROUPS_BY_ROLE must construct and declare
    name/required — catches a role wired up with a broken or half-defined group class."""
    for group_classes in GROUPS_BY_ROLE.values():
        for cls in group_classes:
            instance = cls()
            assert isinstance(instance.name, str) and instance.name
            assert isinstance(instance.required, bool)


@pytest.mark.asyncio
async def test_required_groups_in_default_role_actually_start() -> None:
    """Full lifespan start must leave state markers for every required group in the
    default ("all") role — proves each group's start() ran to completion, not just that
    no exception happened to escape."""
    app = create_app()
    transport = ASGITransport(app=app)

    required_names = {g().name for g in GROUPS_BY_ROLE["all"] if g().required}
    assert required_names == {"infra", "web", "feed_engine", "ops"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            # InfraGroup
            assert app.state.redis is not None
            assert app.state.mongo_db is not None
            # WebGroup
            assert app.state.ws_hub is not None
            assert app.state.command_producer is not None
            # FeedEngineGroup
            assert app.state.order_router is not None
            assert app.state.strategy_host is not None
            assert await app.state.redis.get("engine:status") == "ready"
            # OpsGroup (attribute always set, even if the scheduler itself is None when disabled)
            assert hasattr(app.state, "broker_sync_scheduler")

            resp = await client.get("/healthz")

    assert resp.status_code == 200
