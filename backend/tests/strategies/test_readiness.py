import pytest
from pdp.strategy.readiness import ReadinessComponent, StrategyReadiness

def test_strategy_readiness_evaluate() -> None:
    # All OK
    components = [
        ReadinessComponent("indicators", "ok"),
        ReadinessComponent("bias", "ok"),
    ]
    r = StrategyReadiness.evaluate(components)
    assert r.state == "ok"
    assert not r.is_blocked

    # One blocked
    components = [
        ReadinessComponent("indicators", "ok"),
        ReadinessComponent("chain", "blocked", "PCR missing"),
    ]
    r = StrategyReadiness.evaluate(components)
    assert r.state == "blocked"
    assert r.is_blocked

    # One degraded, no blocks
    components = [
        ReadinessComponent("indicators", "degraded"),
        ReadinessComponent("bias", "ok"),
    ]
    r = StrategyReadiness.evaluate(components)
    assert r.state == "degraded"
    assert not r.is_blocked
