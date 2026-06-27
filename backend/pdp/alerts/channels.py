from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from pdp.alerts.evaluator import AlertNotification

log = structlog.get_logger()


class Channel(ABC):
    """Abstract base class for alert notification channels."""

    @abstractmethod
    async def send(self, alert: AlertNotification, channels: list[str]) -> None:
        """Send alert notification."""
        pass


class WSChannel(Channel):
    """WebSocket channel for real-time alert delivery."""

    def __init__(self, alerts_hub: Any) -> None:
        self.alerts_hub = alerts_hub

    async def send(self, alert: AlertNotification, user_id: str) -> None:
        """Publish alert to WebSocket hub."""
        if self.alerts_hub:
            self.alerts_hub.publish(user_id, alert)


class TelegramChannel(Channel):
    """Telegram channel (stub for v1, deferred implementation)."""

    async def send(self, alert: AlertNotification, chat_id: str) -> None:
        """Log Telegram notification (placeholder)."""
        log.info(
            "telegram_notification_stub",
            alert_id=alert.alert_id,
            security_id=alert.security_id,
            chat_id=chat_id,
        )
        # TODO: Implement Telegram delivery in v2
