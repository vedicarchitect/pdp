"""Tests for the bias-input startup satisfiability check (bias-input-completeness).

A strategy can assign a non-zero weight to a bias input its own configuration
cannot supply -- score_bias() treats a missing value as a silent abstention, so
nothing complains today. check_bias_satisfiability() closes that gap: called at
strategy load, it raises naming the offending weight and the missing requirement.
"""

from __future__ import annotations

import pytest

from pdp.signals.bias import BiasInputUnsatisfiable, BiasWeights, check_bias_satisfiability

_NIFTY_ENTRY = {
    "security_id": "13",
    "exchange_segment": "IDX_I",
    "timeframes": ["5m", "15m", "30m", "1H", "1D", "1w"],
    "indicators": [
        {"family": "ema", "periods": [9, 20, 50]},
        {"family": "pivots"},
        {"family": "period_levels"},
    ],
}


def _watchlist(**overrides) -> list[dict]:
    entry = {**_NIFTY_ENTRY, **overrides}
    return [entry]


def test_missing_1w_timeframe_raises_naming_weight_and_timeframe():
    weights = BiasWeights(w_cam_weekly=1.0, w_cam_daily=0, w_ema_1h=0, w_ema_15m=0, w_ema_5m=0,
                           w_swing=0, w_orb=0, w_pcr=0)
    watchlist = _watchlist(timeframes=["5m", "15m", "30m", "1H", "1D"])  # no 1w

    with pytest.raises(BiasInputUnsatisfiable) as exc:
        check_bias_satisfiability(weights, watchlist, underlying="NIFTY", options_underlyings={"NIFTY"})

    assert "w_cam_weekly" in str(exc.value)
    assert "1w" in str(exc.value)


def test_missing_ema_family_on_1h_raises_naming_family():
    weights = BiasWeights(w_ema_1h=2.5, w_cam_daily=0, w_cam_weekly=0, w_ema_15m=0, w_ema_5m=0,
                           w_swing=0, w_orb=0, w_pcr=0)
    # 1H present but indicators has no ema family (only pivots/period_levels)
    watchlist = _watchlist(indicators=[{"family": "pivots"}, {"family": "period_levels"}])

    with pytest.raises(BiasInputUnsatisfiable) as exc:
        check_bias_satisfiability(weights, watchlist, underlying="NIFTY", options_underlyings={"NIFTY"})

    assert "w_ema_1h" in str(exc.value)
    assert "ema" in str(exc.value)


def test_pcr_without_options_underlying_raises_naming_underlying():
    weights = BiasWeights(w_pcr=1.0, w_cam_daily=0, w_cam_weekly=0, w_ema_1h=0, w_ema_15m=0,
                           w_ema_5m=0, w_swing=0, w_orb=0)
    watchlist = _watchlist()

    with pytest.raises(BiasInputUnsatisfiable) as exc:
        check_bias_satisfiability(weights, watchlist, underlying="SENSEX", options_underlyings={"NIFTY"})

    assert "w_pcr" in str(exc.value)
    assert "SENSEX" in str(exc.value)


def test_zeroed_weight_imposes_no_requirement():
    weights = BiasWeights(w_cam_weekly=0.0, w_cam_daily=0, w_ema_1h=0, w_ema_15m=0, w_ema_5m=0,
                           w_swing=0, w_orb=0, w_pcr=0)
    watchlist = _watchlist(timeframes=["5m"])  # no 1w, but weight is zero

    satisfied = check_bias_satisfiability(
        weights, watchlist, underlying="NIFTY", options_underlyings=set()
    )
    assert satisfied == []


def test_fully_satisfiable_configuration_logs_satisfied_set():
    weights = BiasWeights()  # all default nonzero weights
    watchlist = _watchlist()

    satisfied = check_bias_satisfiability(
        weights, watchlist, underlying="NIFTY", options_underlyings={"NIFTY"}
    )

    assert set(satisfied) == {
        "w_cam_daily", "w_cam_weekly", "w_ema_1h", "w_ema_15m", "w_ema_5m",
        "w_swing", "w_orb", "w_pcr",
    }


def test_swing_requires_period_levels_on_any_timeframe():
    weights = BiasWeights(w_swing=1.0, w_cam_daily=0, w_cam_weekly=0, w_ema_1h=0, w_ema_15m=0,
                           w_ema_5m=0, w_orb=0, w_pcr=0)
    watchlist = _watchlist(indicators=[{"family": "ema", "periods": [9]}])  # no period_levels

    with pytest.raises(BiasInputUnsatisfiable) as exc:
        check_bias_satisfiability(weights, watchlist, underlying="NIFTY", options_underlyings=set())

    assert "w_swing" in str(exc.value)
    assert "period_levels" in str(exc.value)


def test_orb_requires_15m_timeframe():
    weights = BiasWeights(w_orb=1.0, w_cam_daily=0, w_cam_weekly=0, w_ema_1h=0, w_ema_15m=0,
                           w_ema_5m=0, w_swing=0, w_pcr=0)
    watchlist = _watchlist(timeframes=["5m", "1D"])  # no 15m

    with pytest.raises(BiasInputUnsatisfiable) as exc:
        check_bias_satisfiability(weights, watchlist, underlying="NIFTY", options_underlyings=set())

    assert "w_orb" in str(exc.value)
    assert "15m" in str(exc.value)


# ---------------------------------------------------------------------------
# The three shipped live configs must pass once group 3's 1w watchlist entry lands.
# ---------------------------------------------------------------------------


def test_all_shipped_configs_are_satisfiable():
    from pathlib import Path

    from pdp.strategies.directional_strangle import weights_from_params
    from pdp.strategy.registry import load_all

    strategies_dir = Path(__file__).resolve().parents[2] / "strategies"
    configs = [c for c in load_all(strategies_dir) if c.id.startswith("directional_strangle")]
    assert configs, "expected at least the three directional_strangle_* configs"

    for cfg in configs:
        weights = weights_from_params(cfg.params)
        underlying = cfg.params.get("underlying", "NIFTY")
        watchlist = [w.model_dump() for w in cfg.watchlist]
        # options_underlyings is derived from strategy YAMLs themselves (see
        # pdp.strategy.registry.strategy_underlyings) -- every shipped config's
        # own underlying is trivially a member of that derived set.
        check_bias_satisfiability(
            weights, watchlist, underlying=underlying, options_underlyings={underlying}
        )
