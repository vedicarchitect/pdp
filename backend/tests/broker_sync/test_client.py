from __future__ import annotations

from typing import Any

import pytest

from pdp.broker_sync.client import BrokerAccountClient, BrokerSyncError
from pdp.settings import get_settings


def _client_with(monkeypatch: Any, fake_sdk: Any) -> BrokerAccountClient:
    c = BrokerAccountClient(get_settings())
    c._client_id = "CID"
    c._access_token = "TOK"
    monkeypatch.setattr(c, "_ensure_client", lambda: fake_sdk)
    return c


def test_as_rows_normalizes_shapes() -> None:
    assert BrokerAccountClient._as_rows(None) == []
    assert BrokerAccountClient._as_rows([{"a": 1}, "skip", {"b": 2}]) == [{"a": 1}, {"b": 2}]
    assert BrokerAccountClient._as_rows({"a": 1}) == [{"a": 1}]


def test_has_credentials() -> None:
    c = BrokerAccountClient(get_settings())
    c._client_id, c._access_token = "", ""
    assert c.has_credentials is False
    c._client_id, c._access_token = "x", "y"
    assert c.has_credentials is True


class FakeSDK:
    def get_holdings(self) -> dict[str, Any]:
        return {"status": "success", "data": [{"securityId": "1"}]}

    def get_fund_limits(self) -> dict[str, Any]:
        return {"status": "failure", "remarks": "DH-902 invalid data plan", "data": ""}


@pytest.mark.asyncio
async def test_fetch_unwraps_success_envelope(monkeypatch: Any) -> None:
    c = _client_with(monkeypatch, FakeSDK())
    rows = await c.fetch_holdings()
    assert rows == [{"securityId": "1"}]


@pytest.mark.asyncio
async def test_failure_envelope_raises(monkeypatch: Any) -> None:
    c = _client_with(monkeypatch, FakeSDK())
    with pytest.raises(BrokerSyncError):
        await c.fetch_funds()
