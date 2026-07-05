"""Unit tests for the unified strategy registry (`strategy-registry-unification`)."""
from __future__ import annotations

import pytest

from pdp.strategy import unified_registry as ur


def _write_live_yaml(strategies_dir, strategy_id="live_strangle_nifty", underlying="NIFTY"):
    (strategies_dir / f"{strategy_id}.yaml").write_text(
        f"id: {strategy_id}\n"
        "class: pdp.strategies.directional_strangle.DirectionalStrangle\n"
        "watchlist:\n"
        "  - security_id: '13'\n"
        "    exchange_segment: IDX_I\n"
        "    timeframes: [5m]\n"
        "params:\n"
        f"  underlying: {underlying}\n"
        "  lot_size: 65\n"
        "  scale_lots: 2\n"
    )


def _write_strangle_yaml(configs_dir, filename="strangle_test.yaml", underlying="NIFTY", strategy_id=None):
    extra = f"strategy_id: {strategy_id}\n" if strategy_id else ""
    (configs_dir / filename).write_text(
        f"{extra}underlying: {underlying}\n"
        "security_id: '13'\n"
        "timeframe_min: 5\n"
        "take_profit_pct: 0.5\n"
    )


def _write_st_yaml(configs_dir, filename="st_test.yaml"):
    (configs_dir / filename).write_text(
        "st_period: 10\n"
        "st_multiplier: 2.0\n"
        "timeframe_min: 15\n"
    )


def _write_legacy_yaml(configs_dir, filename="legacy_options.yaml"):
    (configs_dir / filename).write_text(
        "type: options-strategy\n"
        "name: Short Straddle\n"
        "underlying: NIFTY\n"
    )


# ── enumeration ──────────────────────────────────────────────────────────────

def test_load_all_enumerates_live_and_backtest_entries(tmp_path):
    strategies_dir = tmp_path / "strategies"
    configs_dir = tmp_path / "configs"
    strategies_dir.mkdir()
    configs_dir.mkdir()
    _write_live_yaml(strategies_dir)
    _write_strangle_yaml(configs_dir)
    _write_st_yaml(configs_dir)

    entries = ur.load_all(strategies_dir, configs_dir)
    by_id = {e.id: e for e in entries}

    assert by_id["live_strangle_nifty"].source == "live"
    assert by_id["live_strangle_nifty"].kind == "strangle"
    assert by_id["live_strangle_nifty"].underlying == "NIFTY"
    assert by_id["strangle_test"].source == "backtest"
    assert by_id["strangle_test"].kind == "strangle"
    assert by_id["st_test"].source == "backtest"
    assert by_id["st_test"].kind == "supertrend"
    assert by_id["st_test"].underlying == "NIFTY"


def test_load_all_skips_unrecognized_dialect(tmp_path):
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    _write_legacy_yaml(configs_dir)

    entries = ur.load_all(tmp_path / "no_strategies", configs_dir)
    assert entries == []


def test_load_all_missing_dirs_returns_empty(tmp_path):
    entries = ur.load_all(tmp_path / "missing_strategies", tmp_path / "missing_configs")
    assert entries == []


# ── canonical id derivation ──────────────────────────────────────────────────

def test_backtest_config_without_explicit_id_uses_filename(tmp_path):
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    _write_strangle_yaml(configs_dir, filename="strangle_nifty_variant.yaml")

    entries = ur.load_all(tmp_path / "no_strategies", configs_dir)
    assert [e.id for e in entries] == ["strangle_nifty_variant"]


def test_backtest_config_explicit_strategy_id_overrides_filename(tmp_path):
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    _write_strangle_yaml(configs_dir, filename="strangle_nifty_variant.yaml", strategy_id="my_custom_id")

    entries = ur.load_all(tmp_path / "no_strategies", configs_dir)
    assert [e.id for e in entries] == ["my_custom_id"]


# ── param schema + bounds ────────────────────────────────────────────────────

def test_param_schema_introspects_name_type_default(tmp_path):
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    _write_strangle_yaml(configs_dir)

    entries = ur.load_all(tmp_path / "no_strategies", configs_dir)
    schema_by_name = {p.name: p for p in entries[0].params_schema}

    assert schema_by_name["timeframe_min"].type == "int"
    assert schema_by_name["timeframe_min"].default == 5
    assert schema_by_name["take_profit_pct"].type == "float"
    assert schema_by_name["take_profit_pct"].default == 0.5


def test_curated_bounds_attached_to_known_knobs(tmp_path):
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    _write_strangle_yaml(configs_dir)

    entries = ur.load_all(tmp_path / "no_strategies", configs_dir)
    schema_by_name = {p.name: p for p in entries[0].params_schema}

    assert schema_by_name["timeframe_min"].bounds == {"enum": [3, 5, 15, 30, 60]}
    assert schema_by_name["take_profit_pct"].bounds == {"min": 0.0, "max": 1.0, "min_exclusive": True}
    # A knob with no curated entry has no bounds, not a fabricated one.
    assert schema_by_name["strike_method"].bounds is None


# ── canonical_id (run label + underlying -> live/paper id) ──────────────────

def test_canonical_id_resolves_strangle_family_by_underlying():
    assert ur.canonical_id(None, "NIFTY") == "directional_strangle_nifty"
    assert ur.canonical_id(None, "BANKNIFTY") == "directional_strangle_banknifty"


def test_canonical_id_defaults_missing_underlying_to_nifty_for_strangle_label():
    assert ur.canonical_id("strangle", None) == "directional_strangle_nifty"


def test_canonical_id_returns_none_when_unresolvable():
    assert ur.canonical_id(None, None) is None
    assert ur.canonical_id("some_other_family", None) is None


# ── register_strategy ────────────────────────────────────────────────────────

def test_register_strategy_persists_yaml_and_is_enumerable(tmp_path):
    configs_dir = tmp_path / "configs"
    entry = ur.register_strategy(
        "my_new_strangle", "strangle", {"underlying": "BANKNIFTY", "timeframe_min": 15},
        configs_dir=configs_dir,
    )
    assert entry.id == "my_new_strangle"
    assert entry.underlying == "BANKNIFTY"
    assert (configs_dir / "my_new_strangle.yaml").exists()

    entries = ur.load_all(tmp_path / "no_strategies", configs_dir)
    assert [e.id for e in entries] == ["my_new_strangle"]


def test_register_strategy_rejects_duplicate_id(tmp_path):
    configs_dir = tmp_path / "configs"
    ur.register_strategy("dup_id", "strangle", {}, configs_dir=configs_dir)
    with pytest.raises(ValueError, match="already registered"):
        ur.register_strategy("dup_id", "strangle", {}, configs_dir=configs_dir)


def test_register_strategy_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError, match="unknown strategy kind"):
        ur.register_strategy("foo", "bogus", {}, configs_dir=tmp_path / "configs")


def test_register_strategy_rejects_invalid_params(tmp_path):
    with pytest.raises(ValueError, match="timeframe_min"):
        ur.register_strategy(
            "bad_cfg", "strangle", {"timeframe_min": -1}, configs_dir=tmp_path / "configs",
        )
