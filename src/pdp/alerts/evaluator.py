from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.alerts.enums import AlertCondition, AlertStatus
from pdp.alerts.models import AlertRecord

log = structlog.get_logger()


class AlertNotification:
    __slots__ = ("alert_id", "condition", "security_id", "status", "threshold", "timestamp")

    def __init__(
        self,
        alert_id: int,
        security_id: str,
        condition: str,
        threshold: Decimal,
        status: AlertStatus,
    ):
        self.alert_id = alert_id
        self.security_id = security_id
        self.condition = condition
        self.threshold = threshold
        self.timestamp = datetime.now(UTC)
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.alert_id,
            "security_id": self.security_id,
            "condition": self.condition,
            "threshold": str(self.threshold),
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
        }


class AlertEvaluator:
    """Evaluates alert conditions on ticks and position updates."""

    def __init__(self, get_session: Callable[[], AsyncSession]):
        self.get_session = get_session
        self._alerts_by_security: dict[str, list[AlertRecord]] = {}
        self._notification_callbacks: list[Callable[[AlertNotification], None]] = []
        self._last_fired: dict[int, bool] = {}  # alert_id -> was_triggered

    def register_notification_callback(
        self, callback: Callable[[AlertNotification], None]
    ) -> None:
        self._notification_callbacks.append(callback)

    async def load_alerts(self) -> None:
        """Load all active alerts from database.

        Degrades gracefully when the alerts table is not yet migrated (mirrors
        PaperBroker._load_open_orders) so app startup is not blocked.
        """
        from sqlalchemy import select
        from sqlalchemy.exc import ProgrammingError

        try:
            async with self.get_session() as session:
                stmt = select(AlertRecord).where(
                    AlertRecord.status.in_([AlertStatus.ARMED.value, AlertStatus.TRIGGERED.value])
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()
        except ProgrammingError:
            log.warning("alerts_table_missing", hint="run alembic upgrade head")
            return

        self._alerts_by_security.clear()
        for row in rows:
            security_id = row.security_id
            if security_id not in self._alerts_by_security:
                self._alerts_by_security[security_id] = []
            self._alerts_by_security[security_id].append(row)
        log.info("alerts_loaded", total=sum(len(v) for v in self._alerts_by_security.values()))

    def evaluate_price(
        self, security_id: str, price: Decimal
    ) -> None:
        """Evaluate price conditions for a security."""
        alerts = self._alerts_by_security.get(security_id, [])
        if not alerts:
            return

        for alert in alerts:
            if alert.condition not in [AlertCondition.PRICE_GT.value, AlertCondition.PRICE_LT.value]:
                continue
            if not self._should_evaluate(alert):
                continue

            should_trigger = self._check_price_condition(alert, price)
            self._update_alert_state(alert, should_trigger)

    def evaluate_greeks(
        self, security_id: str, delta: Decimal | None = None, gamma: Decimal | None = None,
        vega: Decimal | None = None
    ) -> None:
        """Evaluate Greeks conditions for a security."""
        alerts = self._alerts_by_security.get(security_id, [])
        if not alerts:
            return

        for alert in alerts:
            condition = alert.condition
            value = None

            if condition in [AlertCondition.DELTA_GT.value, AlertCondition.DELTA_LT.value]:
                value = delta
            elif condition in [AlertCondition.GAMMA_GT.value, AlertCondition.GAMMA_LT.value]:
                value = gamma
            elif condition in [AlertCondition.VEGA_GT.value, AlertCondition.VEGA_LT.value]:
                value = vega

            if value is None or not self._should_evaluate(alert):
                continue

            should_trigger = self._check_greek_condition(alert, value)
            self._update_alert_state(alert, should_trigger)

    def evaluate_pnl(self, security_id: str, pnl: Decimal) -> None:
        """Evaluate P&L conditions for a security."""
        alerts = self._alerts_by_security.get(security_id, [])
        if not alerts:
            return

        for alert in alerts:
            if alert.condition not in [AlertCondition.PNL_GT.value, AlertCondition.PNL_LT.value]:
                continue
            if not self._should_evaluate(alert):
                continue

            should_trigger = self._check_pnl_condition(alert, pnl)
            self._update_alert_state(alert, should_trigger)

    def _check_price_condition(self, alert: AlertRecord, price: Decimal) -> bool:
        if alert.condition == AlertCondition.PRICE_GT.value:
            return price > alert.threshold
        elif alert.condition == AlertCondition.PRICE_LT.value:
            return price < alert.threshold
        return False

    def _check_greek_condition(self, alert: AlertRecord, value: Decimal) -> bool:
        if alert.condition in [
            AlertCondition.DELTA_GT.value,
            AlertCondition.GAMMA_GT.value,
            AlertCondition.VEGA_GT.value,
        ]:
            return value > alert.threshold
        elif alert.condition in [
            AlertCondition.DELTA_LT.value,
            AlertCondition.GAMMA_LT.value,
            AlertCondition.VEGA_LT.value,
        ]:
            return value < alert.threshold
        return False

    def _check_pnl_condition(self, alert: AlertRecord, pnl: Decimal) -> bool:
        if alert.condition == AlertCondition.PNL_GT.value:
            return pnl > alert.threshold
        elif alert.condition == AlertCondition.PNL_LT.value:
            return pnl < alert.threshold
        return False

    def _should_evaluate(self, alert: AlertRecord) -> bool:
        """Check if alert should be evaluated (debounce)."""
        was_triggered = self._last_fired.get(alert.id, False)
        is_armed = alert.status == AlertStatus.ARMED.value
        return is_armed or was_triggered

    def _update_alert_state(self, alert: AlertRecord, should_trigger: bool) -> None:
        """Update alert state machine and fire notification if needed."""
        was_triggered = self._last_fired.get(alert.id, False)
        is_triggered = alert.status == AlertStatus.TRIGGERED.value

        if should_trigger and not is_triggered:
            # ARMED -> TRIGGERED
            alert.status = AlertStatus.TRIGGERED.value
            self._last_fired[alert.id] = True
            notification = AlertNotification(
                alert.id,
                alert.security_id,
                alert.condition,
                alert.threshold,
                AlertStatus.TRIGGERED,
            )
            self._fire_notification(notification)
        elif not should_trigger and is_triggered:
            # TRIGGERED -> RESOLVED
            alert.status = AlertStatus.RESOLVED.value
            self._last_fired[alert.id] = False

    def _fire_notification(self, notification: AlertNotification) -> None:
        """Fire notification callbacks."""
        for callback in self._notification_callbacks:
            try:
                callback(notification)
            except Exception as exc:
                log.warning("notification_callback_error", alert_id=notification.alert_id, exc=str(exc))
