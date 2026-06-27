from __future__ import annotations

from decimal import Decimal

import pytest

from pdp.alerts.enums import AlertChannel, AlertCondition, AlertStatus
from pdp.alerts.evaluator import AlertEvaluator, AlertNotification
from pdp.alerts.models import AlertRecord


class TestAlertConditionEnum:
    """Test AlertCondition enum validation."""

    def test_price_conditions(self) -> None:
        assert AlertCondition.PRICE_GT.value == "PRICE_GT"
        assert AlertCondition.PRICE_LT.value == "PRICE_LT"

    def test_greek_conditions(self) -> None:
        assert AlertCondition.DELTA_GT.value == "DELTA_GT"
        assert AlertCondition.DELTA_LT.value == "DELTA_LT"
        assert AlertCondition.GAMMA_GT.value == "GAMMA_GT"
        assert AlertCondition.GAMMA_LT.value == "GAMMA_LT"
        assert AlertCondition.VEGA_GT.value == "VEGA_GT"
        assert AlertCondition.VEGA_LT.value == "VEGA_LT"

    def test_pnl_conditions(self) -> None:
        assert AlertCondition.PNL_GT.value == "PNL_GT"
        assert AlertCondition.PNL_LT.value == "PNL_LT"


class TestAlertChannelEnum:
    """Test AlertChannel enum."""

    def test_channels(self) -> None:
        assert AlertChannel.WS.value == "WS"
        assert AlertChannel.TELEGRAM.value == "TELEGRAM"


class TestAlertStatusEnum:
    """Test AlertStatus enum."""

    def test_statuses(self) -> None:
        assert AlertStatus.ARMED.value == "ARMED"
        assert AlertStatus.TRIGGERED.value == "TRIGGERED"
        assert AlertStatus.RESOLVED.value == "RESOLVED"


class TestAlertNotification:
    """Test AlertNotification."""

    def test_to_dict(self) -> None:
        notification = AlertNotification(
            alert_id=1,
            security_id="NSE_EQ_SBIN",
            condition="PRICE_GT",
            threshold=Decimal("500.00"),
            status=AlertStatus.TRIGGERED,
        )
        data = notification.to_dict()
        assert data["id"] == 1
        assert data["security_id"] == "NSE_EQ_SBIN"
        assert data["condition"] == "PRICE_GT"
        assert data["threshold"] == "500.00"
        assert data["status"] == "TRIGGERED"
        assert "timestamp" in data


class TestAlertEvaluator:
    """Test AlertEvaluator."""

    @pytest.fixture
    def evaluator(self) -> AlertEvaluator:
        def mock_get_session():
            pass

        return AlertEvaluator(mock_get_session)

    def test_price_gt_condition(self, evaluator: AlertEvaluator) -> None:
        alert = AlertRecord(
            id=1,
            user_id="user_1",
            security_id="NSE_EQ_SBIN",
            condition=AlertCondition.PRICE_GT.value,
            threshold=Decimal("500.00"),
            channels=["WS"],
            status=AlertStatus.ARMED.value,
        )
        evaluator._alerts_by_security["NSE_EQ_SBIN"] = [alert]

        # Price below threshold — should not trigger
        evaluator.evaluate_price("NSE_EQ_SBIN", Decimal("499.00"))
        assert alert.status == AlertStatus.ARMED.value

        # Price above threshold — should trigger
        evaluator.evaluate_price("NSE_EQ_SBIN", Decimal("501.00"))
        assert alert.status == AlertStatus.TRIGGERED.value

        # Price remains above — should stay triggered
        evaluator.evaluate_price("NSE_EQ_SBIN", Decimal("502.00"))
        assert alert.status == AlertStatus.TRIGGERED.value

        # Price drops below — should resolve
        evaluator.evaluate_price("NSE_EQ_SBIN", Decimal("499.00"))
        assert alert.status == AlertStatus.RESOLVED.value

    def test_price_lt_condition(self, evaluator: AlertEvaluator) -> None:
        alert = AlertRecord(
            id=2,
            user_id="user_1",
            security_id="NSE_EQ_SBIN",
            condition=AlertCondition.PRICE_LT.value,
            threshold=Decimal("500.00"),
            channels=["WS"],
            status=AlertStatus.ARMED.value,
        )
        evaluator._alerts_by_security["NSE_EQ_SBIN"] = [alert]

        # Price above threshold — should not trigger
        evaluator.evaluate_price("NSE_EQ_SBIN", Decimal("501.00"))
        assert alert.status == AlertStatus.ARMED.value

        # Price below threshold — should trigger
        evaluator.evaluate_price("NSE_EQ_SBIN", Decimal("499.00"))
        assert alert.status == AlertStatus.TRIGGERED.value

    def test_greek_conditions(self, evaluator: AlertEvaluator) -> None:
        alert = AlertRecord(
            id=3,
            user_id="user_1",
            security_id="NSE_OPT_SBIN_2600_CE",
            condition=AlertCondition.DELTA_GT.value,
            threshold=Decimal("0.50"),
            channels=["WS"],
            status=AlertStatus.ARMED.value,
        )
        evaluator._alerts_by_security["NSE_OPT_SBIN_2600_CE"] = [alert]

        # Delta below threshold — should not trigger
        evaluator.evaluate_greeks("NSE_OPT_SBIN_2600_CE", delta=Decimal("0.45"))
        assert alert.status == AlertStatus.ARMED.value

        # Delta above threshold — should trigger
        evaluator.evaluate_greeks("NSE_OPT_SBIN_2600_CE", delta=Decimal("0.55"))
        assert alert.status == AlertStatus.TRIGGERED.value

    def test_pnl_conditions(self, evaluator: AlertEvaluator) -> None:
        alert = AlertRecord(
            id=4,
            user_id="user_1",
            security_id="NSE_EQ_SBIN",
            condition=AlertCondition.PNL_GT.value,
            threshold=Decimal("1000.00"),
            channels=["WS"],
            status=AlertStatus.ARMED.value,
        )
        evaluator._alerts_by_security["NSE_EQ_SBIN"] = [alert]

        # P&L below threshold — should not trigger
        evaluator.evaluate_pnl("NSE_EQ_SBIN", Decimal("500.00"))
        assert alert.status == AlertStatus.ARMED.value

        # P&L above threshold — should trigger
        evaluator.evaluate_pnl("NSE_EQ_SBIN", Decimal("1500.00"))
        assert alert.status == AlertStatus.TRIGGERED.value

    def test_notification_callback(self, evaluator: AlertEvaluator) -> None:
        notifications: list[AlertNotification] = []

        def capture_notification(notification: AlertNotification) -> None:
            notifications.append(notification)

        evaluator.register_notification_callback(capture_notification)

        alert = AlertRecord(
            id=5,
            user_id="user_1",
            security_id="NSE_EQ_SBIN",
            condition=AlertCondition.PRICE_GT.value,
            threshold=Decimal("500.00"),
            channels=["WS"],
            status=AlertStatus.ARMED.value,
        )
        evaluator._alerts_by_security["NSE_EQ_SBIN"] = [alert]

        # Evaluate and trigger
        evaluator.evaluate_price("NSE_EQ_SBIN", Decimal("501.00"))

        assert len(notifications) == 1
        assert notifications[0].alert_id == 5
        assert notifications[0].status == AlertStatus.TRIGGERED
