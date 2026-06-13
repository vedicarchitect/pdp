from decimal import Decimal
import pytest

from pdp.settings import BacktestCommissionSettings
from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator


@pytest.fixture
def settings():
    return BacktestCommissionSettings()


@pytest.fixture
def calc(settings):
    return CommissionCalculator(settings)


def test_sell_side(calc):
    turnover = Decimal("7500.0")  # 1 lot NIFTY (75) at 100
    res = calc.calculate("sell", turnover)
    
    assert float(res.brokerage) == pytest.approx(20.0, abs=0.01)
    assert float(res.stt) == pytest.approx(7.5, abs=0.01)
    assert float(res.txn_charge) == pytest.approx(2.66, abs=0.01)
    assert float(res.sebi) == pytest.approx(0.08, abs=0.01)
    assert float(res.stamp_duty) == pytest.approx(0.0, abs=0.01)
    assert float(res.gst) == pytest.approx(4.09, abs=0.01)
    assert float(res.total_inr) == pytest.approx(34.33, abs=0.01)


def test_buy_side(calc):
    turnover = Decimal("7500.0")
    res = calc.calculate("buy", turnover)
    
    assert float(res.stt) == 0.0
    assert float(res.stamp_duty) == pytest.approx(0.3, abs=0.01)
    assert float(res.total_inr) == pytest.approx(27.13, abs=0.01)


def test_zero_turnover(calc):
    res = calc.calculate("buy", Decimal("0.0"))
    
    assert float(res.brokerage) == 20.0
    assert float(res.stt) == 0.0
    assert float(res.txn_charge) == 0.0
    assert float(res.sebi) == 0.0
    assert float(res.stamp_duty) == 0.0
    assert float(res.gst) == 0.0
    assert float(res.total_inr) == 20.0


def test_null_calculator(settings):
    null_calc = NullCommissionCalculator(settings)
    
    res = null_calc.calculate("sell", Decimal("7500.0"))
    assert float(res.brokerage) == 0.0
    assert float(res.stt) == 0.0
    assert float(res.txn_charge) == 0.0
    assert float(res.sebi) == 0.0
    assert float(res.stamp_duty) == 0.0
    assert float(res.gst) == 0.0
    assert float(res.total_inr) == 0.0
