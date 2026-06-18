"""Tests for OptionsStrategyConfig parsing and validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from pdp.backtest.options_strategy import (
    LegConfig,
    OptionsStrategyConfig,
    RiskConfig,
    StrikeSelection,
)

EXAMPLE_YAML = Path(__file__).parent.parent.parent / "backtest" / "configs" / "options_short_straddle.yaml"


def test_parse_valid_config_from_yaml():
    config = OptionsStrategyConfig.from_yaml(EXAMPLE_YAML)
    assert config.type == "options-strategy"
    assert config.name == "Short Straddle 9:20"
    assert config.underlying == "NIFTY"
    assert config.expiry_selection == "weekly"
    assert config.entry.time_ist == "09:20"
    assert config.exit.time_ist == "15:10"
    assert len(config.entry.legs) == 2
    assert config.lot_size == 75
    assert config.commissions is True


def test_parse_legs():
    config = OptionsStrategyConfig.from_yaml(EXAMPLE_YAML)
    ce_leg, pe_leg = config.entry.legs
    assert ce_leg.type == "CE"
    assert ce_leg.side == "SELL"
    assert ce_leg.lots == 1
    assert ce_leg.strike_selection.method == "atm_offset"
    assert ce_leg.strike_selection.offset == 0
    assert pe_leg.type == "PE"
    assert pe_leg.side == "SELL"


def test_parse_risk_config():
    config = OptionsStrategyConfig.from_yaml(EXAMPLE_YAML)
    risk = config.risk
    assert risk.combined_sl is not None
    assert risk.combined_sl.type == "points"
    assert risk.combined_sl.value == 50
    assert risk.combined_target is not None
    assert risk.combined_target.value == 30
    assert risk.trailing_sl.enabled is True
    assert risk.trailing_sl.trail_after == 20
    assert risk.trailing_sl.trail_step == 5
    assert risk.re_entry.enabled is True
    assert risk.re_entry.max_count == 2


def test_parse_inline_dict():
    data = {
        "type": "options-strategy",
        "name": "Test Strategy",
        "underlying": "NIFTY",
        "date_range": {"from": "2026-01-01", "to": "2026-03-01"},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "lots": 2, "strike_selection": {"method": "atm_offset", "offset": 1}},
            ],
        },
        "exit": {"time_ist": "15:10"},
        "risk": {},
        "lot_size": 75,
        "commissions": False,
    }
    config = OptionsStrategyConfig.model_validate(data)
    assert config.name == "Test Strategy"
    assert config.entry.legs[0].lots == 2
    assert config.entry.legs[0].strike_selection.offset == 1
    assert config.commissions is False


def test_missing_entry_time_raises():
    data = {
        "type": "options-strategy",
        "name": "Bad Config",
        "underlying": "NIFTY",
        "date_range": {"from": "2026-01-01", "to": "2026-03-01"},
        "entry": {
            "legs": [{"type": "CE", "side": "SELL"}],
        },
        "exit": {"time_ist": "15:10"},
    }
    with pytest.raises(Exception):
        OptionsStrategyConfig.model_validate(data)


def test_by_premium_strike_selection():
    data = {
        "type": "options-strategy",
        "name": "By Premium",
        "underlying": "NIFTY",
        "date_range": {"from": "2026-01-01", "to": "2026-03-01"},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "strike_selection": {"method": "by_premium", "target_premium": 80.0}},
            ],
        },
        "exit": {"time_ist": "15:10"},
    }
    config = OptionsStrategyConfig.model_validate(data)
    leg = config.entry.legs[0]
    assert leg.strike_selection.method == "by_premium"
    assert leg.strike_selection.target_premium == 80.0


def test_date_range_parsing():
    config = OptionsStrategyConfig.from_yaml(EXAMPLE_YAML)
    from datetime import date
    assert config.date_range.from_ == date(2026, 1, 1)
    assert config.date_range.to == date(2026, 6, 1)
