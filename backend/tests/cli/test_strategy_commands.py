"""Unit tests for the `pdp strategy` CLI (REST client over a running API)."""
from __future__ import annotations

from click.testing import CliRunner

import pdp.cli.strategy_commands as mod
from pdp.cli.strategy_commands import strategy


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise mod.httpx.HTTPStatusError("err", request=None, response=self)


class _FakeClient:
    last_get: str | None = None
    last_post: str | None = None

    def __init__(self, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, path):
        _FakeClient.last_get = path
        return _Resp([{"id": "supertrend_short", "status": "STOPPED", "dropped_ticks": 0}])

    def post(self, path):
        _FakeClient.last_post = path
        return _Resp({"id": "supertrend_short", "status": "RUNNING"})


def test_list(monkeypatch):
    monkeypatch.setattr(mod.httpx, "Client", _FakeClient)
    result = CliRunner().invoke(strategy, ["list"])
    assert result.exit_code == 0
    assert "supertrend_short" in result.output
    assert _FakeClient.last_get == "/api/v1/strategies"


def test_start_hits_start_endpoint(monkeypatch):
    monkeypatch.setattr(mod.httpx, "Client", _FakeClient)
    result = CliRunner().invoke(strategy, ["start", "supertrend_short"])
    assert result.exit_code == 0
    assert "RUNNING" in result.output
    assert _FakeClient.last_post == "/api/v1/strategies/supertrend_short/start"


def test_stop_hits_stop_endpoint(monkeypatch):
    monkeypatch.setattr(mod.httpx, "Client", _FakeClient)
    result = CliRunner().invoke(strategy, ["stop", "supertrend_short"])
    assert result.exit_code == 0
    assert _FakeClient.last_post == "/api/v1/strategies/supertrend_short/stop"


def test_unreachable_api_is_friendly_error(monkeypatch):
    class _Boom:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, path):
            raise mod.httpx.ConnectError("connection refused")

    monkeypatch.setattr(mod.httpx, "Client", _Boom)
    result = CliRunner().invoke(strategy, ["list"])
    assert result.exit_code != 0
    assert "could not reach PDP API" in result.output
