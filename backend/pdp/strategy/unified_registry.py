"""Canonical-id strategy registry spanning live ``strategies/*.yaml`` configs and
backtest ``backtest/configs/*.yaml`` configs.

Live and backtest strategies are configured through different, independently-evolving
loaders (`pdp.strategy.registry` — pydantic `StrategyConfig`; `pdp.backtest.strangle_config`
and `pdp.backtest.strategy_config` — dataclasses). This module is a thin facade that adapts
both into one canonical-id-keyed list of `StrategyEntry`, without changing how either side
loads or executes. See `openspec/changes/strategy-registry-unification/design.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pdp.backtest.strangle_config import StrangleConfig
from pdp.backtest.strategy_config import StrategyConfig as BacktestSTConfig
from pdp.strategy.registry import load_all as _load_live_configs

LIVE_STRATEGIES_DIR = Path("strategies")
BACKTEST_CONFIGS_DIR = Path("backtest/configs")

# Curated bounds for editable knobs with well-known sensible ranges. Keyed by param name —
# applies across engines since the same knob name carries the same meaning everywhere it
# appears (e.g. `timeframe_min` means the same thing in the strangle and SuperTrend engines).
# Additive metadata only; the schema itself is introspected from each config's own fields.
PARAM_BOUNDS: dict[str, dict[str, Any]] = {
    "timeframe_min": {"enum": [3, 5, 15, 30, 60]},
    "take_profit_pct": {"min": 0.0, "max": 1.0, "min_exclusive": True},
    "pct_stop_half": {"min": 0.0, "max": 1.0, "min_exclusive": True},
    "pct_stop_all": {"min": 0.0, "max": 1.0, "min_exclusive": True},
    "st_period": {"min": 1},
    "st_multiplier": {"min": 0.0, "min_exclusive": True},
    "moneyness": {"min": -5, "max": 5},
    "otm_steps": {"min": 0, "max": 10},
    "scale_lots": {"min": 1, "max": 20},
    "base_lots": {"min": 1},
    "add_lots": {"min": 0},
    "max_lots": {"min": 1},
    "lot_size": {"min": 1},
    "strike_step": {"min": 1},
    "hedge_prem_min": {"min": 0.0, "min_exclusive": True},
    "hedge_prem_max": {"min": 0.0, "min_exclusive": True},
    "day_loss_limit": {"min": 0.0, "min_exclusive": True},
    "day_stop": {"min": 0.0, "min_exclusive": True},
    "dte_max": {"min": 0},
}


@dataclass
class ParamSpec:
    name: str
    type: str
    default: Any
    bounds: dict[str, Any] | None = None


@dataclass
class StrategyEntry:
    id: str
    kind: str
    underlying: str | None
    source: str  # "live" | "backtest"
    params_schema: list[ParamSpec]
    defaults: dict[str, Any]
    config_path: str


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "list"
    return "str"


def _params_schema_from_dict(values: dict[str, Any]) -> list[ParamSpec]:
    return [
        ParamSpec(name=name, type=_infer_type(value), default=value, bounds=PARAM_BOUNDS.get(name))
        for name, value in values.items()
    ]


def _load_live_entries(strategies_dir: Path) -> list[StrategyEntry]:
    if not strategies_dir.exists():
        return []
    entries: list[StrategyEntry] = []
    for cfg in _load_live_configs(strategies_dir):
        kind = "strangle" if "strangle" in cfg.cls.lower() else cfg.cls.rpartition(".")[-1].lower()
        entries.append(StrategyEntry(
            id=cfg.id,
            kind=kind,
            underlying=cfg.params.get("underlying"),
            source="live",
            params_schema=_params_schema_from_dict(cfg.params),
            defaults=dict(cfg.params),
            config_path=str(strategies_dir / f"{cfg.id}.yaml"),
        ))
    return entries


def _canonical_backtest_id(path: Path, raw: dict[str, Any]) -> str:
    explicit = raw.get("strategy_id")
    return str(explicit) if explicit else path.stem


def _load_backtest_entries(configs_dir: Path) -> list[StrategyEntry]:
    if not configs_dir.exists():
        return []
    strangle_fields = set(StrangleConfig.__dataclass_fields__)
    st_fields = set(BacktestSTConfig.__dataclass_fields__)
    entries: list[StrategyEntry] = []
    for path in sorted(configs_dir.glob("*.yaml")):
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        body: dict[str, Any] = {k: v for k, v in raw.items() if k != "strategy_id"}
        keys = set(body)
        canonical = _canonical_backtest_id(path, raw)
        if keys <= strangle_fields:
            cfg = StrangleConfig.from_dict(body)
            defaults = cfg.to_dict()
            entries.append(StrategyEntry(
                id=canonical, kind="strangle", underlying=cfg.underlying, source="backtest",
                params_schema=_params_schema_from_dict(defaults), defaults=defaults,
                config_path=str(path),
            ))
        elif keys <= st_fields:
            cfg = BacktestSTConfig.from_dict(body)
            defaults = cfg.to_dict()
            entries.append(StrategyEntry(
                id=canonical, kind="supertrend", underlying="NIFTY", source="backtest",
                params_schema=_params_schema_from_dict(defaults), defaults=defaults,
                config_path=str(path),
            ))
        # else: unrecognized dialect (e.g. the legacy options-strategy YAML) — not yet
        # unified behind this registry; skip rather than guess.
    return entries


def load_all(
    strategies_dir: Path = LIVE_STRATEGIES_DIR,
    configs_dir: Path = BACKTEST_CONFIGS_DIR,
) -> list[StrategyEntry]:
    """Enumerate every registered strategy across live configs and backtest configs."""
    return _load_live_entries(strategies_dir) + _load_backtest_entries(configs_dir)


def register_strategy(
    strategy_id: str,
    kind: str,
    params: dict[str, Any],
    *,
    configs_dir: Path = BACKTEST_CONFIGS_DIR,
    strategies_dir: Path = LIVE_STRATEGIES_DIR,
) -> StrategyEntry:
    """Register a new strategy, persisted as a `backtest/configs/<strategy_id>.yaml` record.

    Validates *params* against the matching engine's config dataclass (rejects unknown keys
    and out-of-range values via that class's own `validate()`), then writes a YAML file
    carrying an explicit `strategy_id` key. The new entry is picked up by the next
    `load_all()` call — no code change or restart required — and its `defaults` are
    launch-ready as a `POST /runs` request body.
    """
    existing_ids = {e.id for e in load_all(strategies_dir, configs_dir)}
    if strategy_id in existing_ids:
        raise ValueError(f"strategy id {strategy_id!r} is already registered")

    if kind == "strangle":
        cfg: StrangleConfig | BacktestSTConfig = StrangleConfig.from_dict(params)
        underlying = cfg.underlying
    elif kind == "supertrend":
        cfg = BacktestSTConfig.from_dict(params)
        underlying = "NIFTY"
    else:
        raise ValueError(f"unknown strategy kind {kind!r}; expected 'strangle' or 'supertrend'")

    configs_dir.mkdir(parents=True, exist_ok=True)
    path = configs_dir / f"{strategy_id}.yaml"
    if path.exists():
        raise FileExistsError(f"a strategy config file already exists at {path}")

    defaults = cfg.to_dict()
    doc = dict(defaults)
    doc["strategy_id"] = strategy_id
    with path.open("w") as f:
        yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=True)

    return StrategyEntry(
        id=strategy_id, kind=kind, underlying=underlying, source="backtest",
        params_schema=_params_schema_from_dict(defaults), defaults=defaults,
        config_path=str(path),
    )


def canonical_id(
    run_label: str | None,
    underlying: str | None,
    *,
    live_entries: list[StrategyEntry] | None = None,
) -> str | None:
    """Map a backtest run's coarse family label + underlying to a canonical live/paper id.

    An explicit underlying resolves against whichever live entry shares that family's kind
    (defaulting the family to "strangle", the one live family that exists today, when
    *run_label* is absent). A missing underlying only resolves for a "strangle"-family run,
    defaulting to NIFTY — the only underlying backtested before multi-index support, and the
    interim heuristic this registry lookup replaces (`pdp.backtest.paper_compare`).
    """
    if underlying:
        u = str(underlying).upper()
    elif run_label == "strangle":
        u = "NIFTY"
    else:
        return None
    kind = run_label or "strangle"
    if live_entries is None:
        live_entries = _load_live_entries(LIVE_STRATEGIES_DIR)
    for entry in live_entries:
        if entry.kind == kind and (entry.underlying or "").upper() == u:
            return entry.id
    return None
