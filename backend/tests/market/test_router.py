"""TickRouter has no in-process WSHub coupling (api-worker-decoupling task 3.2).

WS fan-out is the API process's job: TickRouter only publishes to Redis
(pub/sub `tick.<id>` + stream `bars.<id>.<tf>`); MarketBridge in the API
process is the sole consumer that talks to WSHub.
"""

from __future__ import annotations

import inspect

from pdp.market.router import TickRouter


def test_tick_router_init_has_no_ws_hub_param():
    params = inspect.signature(TickRouter.__init__).parameters
    assert "ws_hub" not in params


def test_tick_router_instance_has_no_ws_hub_attribute():
    router = TickRouter()
    assert not hasattr(router, "ws_hub")
    assert not hasattr(router, "_ws_hub")
