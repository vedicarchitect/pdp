"""Web Push (VAPID) delivery + subscription management."""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, select

from pdp.events.models_db import PushSubscription

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.events.models import Event
    from pdp.settings import Settings

log = structlog.get_logger()


class WebPushSender:
    """Sends events as Web Push notifications; prunes dead subscriptions."""

    def __init__(self, settings: Settings, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._settings = settings
        self._session_maker = session_maker

    @property
    def configured(self) -> bool:
        return bool(self._settings.EVENTS_VAPID_PRIVATE_KEY and self._settings.EVENTS_VAPID_PUBLIC_KEY)

    async def add_subscription(self, endpoint: str, p256dh: str, auth: str) -> None:
        async with self._session_maker() as session:
            existing = await session.get(PushSubscription, endpoint)
            if existing is None:
                session.add(PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth))
                await session.commit()

    async def _all(self) -> list[PushSubscription]:
        async with self._session_maker() as session:
            result = await session.execute(select(PushSubscription))
            return list(result.scalars().all())

    async def _prune(self, endpoint: str) -> None:
        async with self._session_maker() as session:
            await session.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
            await session.commit()

    async def send(self, event: Event) -> None:
        if not self.configured:
            return
        subs = await self._all()
        if not subs:
            return
        payload = json.dumps({
            "title": f"[{event.severity.value}] {event.title}",
            "body": event.message,
            "tag": event.event_type.value,
            "data": event.to_dict(),
        })
        for sub in subs:
            await asyncio.to_thread(self._send_one, sub, payload)

    def _send_one(self, sub: PushSubscription, payload: str) -> None:
        from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]

        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=self._settings.EVENTS_VAPID_PRIVATE_KEY,
                vapid_claims={"sub": self._settings.EVENTS_VAPID_SUBJECT},
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                # Subscription gone — schedule pruning.
                try:
                    asyncio.get_running_loop().create_task(self._prune(sub.endpoint))
                except RuntimeError:
                    pass
                log.info("push_subscription_pruned", endpoint=sub.endpoint[:40])
            else:
                log.warning("web_push_failed", status=status, exc=str(exc))
