"""Config-parity guards for the directional strangle strategy (indicator-history-depth task 1.5).

The strangle *backtest* configs (``backend/backtest/configs/strangle_*_hedged.yaml``,
``StrangleConfig``) have no ``ema``/``suite_indicators`` field: the backtest's EMA(9/20/50)
bias-vote input is assembled by ``pdp.backtest.strangle_loader``'s own ``EMATracker`` replay,
never by that YAML. There is therefore no "live vs backtest ema periods" YAML field to diff —
the two paths already share the conversion logic via
``pdp.signals.bias.tf_ema_from_values()`` (see ``tests/signals`` and ``tests/backtest``), not
via a shared config file. This module instead guards the invariants that actually hold:

  - Every live strangle underlying configures EMA(200) for the console/matrix requirement.
  - The live watchlist's ``ema`` periods are a superset of the bias engine's fixed 9/20/50
    requirement — if not, ``tf_ema_from_values`` silently drops that timeframe's EMA vote.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "strategies"
_UNDERLYINGS = ["nifty", "banknifty", "sensex"]

# The bias engine's fixed alignment-vote requirement (pdp/signals/bias.py TimeframeEMA,
# pdp/backtest/strangle_loader.py _EMA_PERIODS). Not derived from config on purpose —
# it is strategy business logic, not a generic indicator-suite setting.
_BIAS_VOTE_EMA_PERIODS = {9, 20, 50}


def _ema_periods(underlying: str) -> list[int]:
    path = _STRATEGIES_DIR / f"directional_strangle_{underlying}.yaml"
    cfg = yaml.safe_load(path.read_text())
    watchlist = cfg["watchlist"][0]
    for ind in watchlist["indicators"]:
        if ind.get("family") == "ema":
            return list(ind["periods"])
    raise AssertionError(f"no ema family configured in {path}")


class TestLiveConfigEmaPeriods:
    def test_ema_200_configured_for_every_underlying(self):
        for u in _UNDERLYINGS:
            periods = _ema_periods(u)
            assert 200 in periods, f"{u}: ema family missing period 200"

    def test_bias_vote_periods_are_a_subset(self):
        """9/20/50 must always be present, or tf_ema_from_values silently drops the vote."""
        for u in _UNDERLYINGS:
            periods = set(_ema_periods(u))
            assert _BIAS_VOTE_EMA_PERIODS <= periods, (
                f"{u}: ema periods {sorted(periods)} missing bias-vote requirement "
                f"{sorted(_BIAS_VOTE_EMA_PERIODS)}"
            )
