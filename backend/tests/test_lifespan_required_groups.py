"""A live-trading group that cannot start must abort startup, not log-and-continue."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

import pdp.main as main_mod


class _Recorder:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []


class _Group:
    def __init__(self, name: str, required: bool, rec: _Recorder, boom: bool = False) -> None:
        self.name = name
        self.required = required
        self._rec = rec
        self._boom = boom

    async def start(self, app: FastAPI) -> None:
        if self._boom:
            raise RuntimeError(f"{self.name} failed")
        self._rec.started.append(self.name)

    async def stop(self, app: FastAPI) -> None:
        self._rec.stopped.append(self.name)


def _install(monkeypatch: pytest.MonkeyPatch, groups: list[Any]) -> None:
    import pdp.runtime.groups as groups_mod

    monkeypatch.setattr(groups_mod, "GROUPS_BY_ROLE", {"all": [lambda g=g: g for g in groups]})


@pytest.mark.asyncio
async def test_required_group_failure_aborts_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder()
    ok = _Group("infra", required=True, rec=rec)
    bad = _Group("ops", required=True, rec=rec, boom=True)
    never = _Group("later", required=False, rec=rec)
    _install(monkeypatch, [ok, bad, never])

    app = FastAPI()
    with pytest.raises(RuntimeError, match="ops failed"):
        async with main_mod.lifespan(app):
            pass

    assert rec.started == ["infra"]
    assert "later" not in rec.started
    assert rec.stopped == ["infra"], "already-started groups must be torn down"


@pytest.mark.asyncio
async def test_optional_group_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder()
    bad = _Group("job_runner", required=False, rec=rec, boom=True)
    ok = _Group("ops", required=True, rec=rec)
    _install(monkeypatch, [bad, ok])

    app = FastAPI()
    async with main_mod.lifespan(app):
        pass

    assert rec.started == ["ops"]
    assert rec.stopped == ["ops"]
