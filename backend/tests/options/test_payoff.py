import math

import pytest

from pdp.options.payoff import PayoffLeg, build_payoff


def test_long_straddle_payoff():
    # Long straddle: Buy ATM CE and Buy ATM PE
    legs = [
        PayoffLeg(strike=100.0, expiry="2026-06-25", option_type="CE", side="BUY", lots=1, premium=5.0, iv=0.2),
        PayoffLeg(strike=100.0, expiry="2026-06-25", option_type="PE", side="BUY", lots=1, premium=5.0, iv=0.2),
    ]
    res = build_payoff(legs, spot=100.0, lot_size=10, days_to_expiry=10)
    
    assert res.max_loss == pytest.approx(-100.0, abs=2.0)  # Total premium paid = 10 * 10 = 100
    assert res.max_profit is None  # Unbounded profit
    
    # Breakevens should be around 100 ± 10
    assert any(math.isclose(b, 90.0, abs_tol=1.0) for b in res.breakevens)
    assert any(math.isclose(b, 110.0, abs_tol=1.0) for b in res.breakevens)
    
def test_bull_call_spread():
    # Buy 100 CE for 5, Sell 110 CE for 2
    legs = [
        PayoffLeg(strike=100.0, expiry="2026-06-25", option_type="CE", side="BUY", lots=1, premium=5.0, iv=0.2),
        PayoffLeg(strike=110.0, expiry="2026-06-25", option_type="CE", side="SELL", lots=1, premium=2.0, iv=0.2),
    ]
    res = build_payoff(legs, spot=100.0, lot_size=10, days_to_expiry=10)
    
    # Max loss = net premium paid = (5 - 2) * 10 = 30
    assert res.max_loss == pytest.approx(-30.0, abs=2.0)
    # Max profit = (spread - net premium) * lot_size = (10 - 3) * 10 = 70
    assert res.max_profit == pytest.approx(70.0, abs=2.0)
    
    # Breakeven = 100 + 3 = 103
    assert any(math.isclose(b, 103.0, abs_tol=1.0) for b in res.breakevens)

def test_iron_condor():
    # Sell 90 PE, Buy 80 PE, Sell 110 CE, Buy 120 CE
    legs = [
        PayoffLeg(strike=80.0, expiry="2026-06-25", option_type="PE", side="BUY", lots=1, premium=1.0, iv=0.2),
        PayoffLeg(strike=90.0, expiry="2026-06-25", option_type="PE", side="SELL", lots=1, premium=3.0, iv=0.2),
        PayoffLeg(strike=110.0, expiry="2026-06-25", option_type="CE", side="SELL", lots=1, premium=3.0, iv=0.2),
        PayoffLeg(strike=120.0, expiry="2026-06-25", option_type="CE", side="BUY", lots=1, premium=1.0, iv=0.2),
    ]
    res = build_payoff(legs, spot=100.0, lot_size=10, days_to_expiry=10)
    
    # Net credit = (3 + 3) - (1 + 1) = 4
    # Max profit = 4 * 10 = 40
    assert res.max_profit == pytest.approx(40.0, abs=2.0)
    # Max loss = (spread - net credit) * lot_size = (10 - 4) * 10 = 60
    assert res.max_loss == pytest.approx(-60.0, abs=2.0)
    
    assert len(res.breakevens) == 2
    assert any(math.isclose(b, 86.0, abs_tol=1.0) for b in res.breakevens)
    assert any(math.isclose(b, 114.0, abs_tol=1.0) for b in res.breakevens)

def test_single_leg_naked_call_buy():
    legs = [
        PayoffLeg(strike=100.0, expiry="2026-06-25", option_type="CE", side="BUY", lots=1, premium=5.0, iv=0.2),
    ]
    res = build_payoff(legs, spot=100.0, lot_size=10, days_to_expiry=10)
    
    assert res.max_loss == -50.0
    assert res.max_profit is None
    assert 105.0 in res.breakevens

def test_pop_bounds():
    # ATM call buy: POP should be < 50%
    legs = [
        PayoffLeg(strike=100.0, expiry="2026-06-25", option_type="CE", side="BUY", lots=1, premium=5.0, iv=0.2),
    ]
    res = build_payoff(legs, spot=100.0, lot_size=10, days_to_expiry=10)
    assert 0.0 <= res.probability_of_profit <= 1.0

def test_margin_estimate_short():
    # Naked short call
    legs = [
        PayoffLeg(strike=100.0, expiry="2026-06-25", option_type="CE", side="SELL", lots=1, premium=5.0, iv=0.2),
    ]
    res = build_payoff(legs, spot=100.0, lot_size=10, days_to_expiry=10)
    
    # Unbounded loss -> should have a positive margin estimate
    assert res.max_loss is None
    assert res.margin_estimate > 0
    assert res.margin_is_approximate is True

def test_empty_legs():
    res = build_payoff([], spot=100.0, lot_size=10)
    assert res.pnl_curve == []
    assert res.breakevens == []
    assert res.max_profit == 0.0
    assert res.max_loss == 0.0
    assert res.probability_of_profit == 0.0
