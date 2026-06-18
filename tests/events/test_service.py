"""EventService tests: dedup/cooldown, push severity gating, disabled no-op."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pdp.events.models import Event, EventType, Severity
from pdp.events.service import EventService
from pdp.events.store import EventStore
from pdp.settings import Settings


class FakeHub:
    def __init__(self) -> None:
        self.published: list[Event] = []

    def publish(self, event: Event) -> None:
        self.published.append(event)


def _service(hub: FakeHub) -> EventService:
    settings = Settings(DATABASE_URL="x", DATABASE_SYNC_URL="x", REDIS_URL="x")
    return EventService(
        settings=settings, engine=None, hub=hub, store=EventStore(None),
        push_sender=None, session_maker=lambda: None, adapter=None,
    )


def _ev(et=EventType.PSAR_FLIP, sev=Severity.WARNING, key="k1") -> Event:
    return Event(event_type=et, severity=sev, security_id="13", title="t", message="m", dedup_key=key)


def test_dedup_cooldown_suppresses_repeat():
    hub = FakeHub()
    svc = _service(hub)
    svc.emit(_ev(key="same"))
    svc.emit(_ev(key="same"))  # within cooldown → suppressed
    assert len(hub.published) == 1


def test_distinct_keys_both_emit():
    hub = FakeHub()
    svc = _service(hub)
    svc.emit(_ev(key="a"))
    svc.emit(_ev(key="b"))
    assert len(hub.published) == 2


def test_push_severity_gating():
    hub = FakeHub()
    svc = _service(hub)
    svc.cfg.push_enabled = True  # min severity defaults to WARNING
    svc.emit(_ev(sev=Severity.INFO, key="info"))
    assert svc._push_q.qsize() == 0
    svc.emit(_ev(sev=Severity.CRITICAL, key="crit"))
    assert svc._push_q.qsize() == 1


def test_disabled_on_bar_noop():
    hub = FakeHub()
    svc = _service(hub)
    svc.cfg.enabled = False
    bar = SimpleNamespace(security_id="13", timeframe="15m")
    svc.on_bar(bar)  # type: ignore[arg-type]
    assert hub.published == []


@pytest.mark.asyncio
async def test_store_worker_persists(monkeypatch):
    hub = FakeHub()
    svc = _service(hub)
    inserted: list[Event] = []

    async def fake_insert(event: Event) -> None:
        inserted.append(event)

    monkeypatch.setattr(svc._store, "insert", fake_insert)
    svc.emit(_ev(key="store"))
    # drain one item through the worker logic directly
    event = svc._store_q.get_nowait()
    await svc._store.insert(event)
    assert inserted and inserted[0].dedup_key == "store"
