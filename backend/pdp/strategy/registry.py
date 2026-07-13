from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    from pdp.strategy.abc import Strategy


class MLSignalConfig(BaseModel):
    """Opt-in ML signal configuration for a watchlist entry."""
    enabled: bool = False
    version: str = ""          # artifact version to serve; empty = use ML_ACTIVE_VERSION
    head: str = "directional"  # "directional" or "expiry"


class WatchlistEntry(BaseModel):
    security_id: str
    exchange_segment: str
    timeframes: list[str]
    indicators: list[dict[str, Any]] = []
    ml_signal: MLSignalConfig = MLSignalConfig()


class RiskConfig(BaseModel):
    max_open_orders: int = 5
    max_daily_loss_inr: float = 10_000.0


class StrategyConfig(BaseModel):
    id: str
    cls: str = ""  # populated from YAML "class" key
    watchlist: list[WatchlistEntry]
    params: dict[str, Any] = {}
    risk: RiskConfig = RiskConfig()

    @field_validator("cls")
    @classmethod
    def _cls_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("'class' field is required")
        return v

    model_config = {"populate_by_name": True}


def _load_yaml(path: Path) -> StrategyConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML key is "class" but that's a Python keyword — map to "cls"
    if "class" in raw and "cls" not in raw:
        raw["cls"] = raw.pop("class")
    return StrategyConfig.model_validate(raw)


def load_all(strategies_dir: Path) -> list[StrategyConfig]:
    """Load and validate all *.yaml configs from *strategies_dir*."""
    configs: list[StrategyConfig] = []
    for path in sorted(strategies_dir.glob("*.yaml")):
        configs.append(_load_yaml(path))
    return configs


def load_one(strategy_id: str, strategies_dir: Path) -> StrategyConfig:
    """Load a single strategy config by id, re-reading from disk each call."""
    path = strategies_dir / f"{strategy_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no config found for strategy {strategy_id!r} at {path}")
    cfg = _load_yaml(path)
    if cfg.id != strategy_id:
        raise ValueError(
            f"YAML id {cfg.id!r} does not match requested strategy_id {strategy_id!r}"
        )
    return cfg


def import_strategy_class(dotted: str):  # type: ignore[return]
    """Import and return the Strategy subclass at *dotted* path."""
    module_path, _, class_name = dotted.rpartition(".")
    if not module_path:
        raise ImportError(f"invalid class path {dotted!r}: must be dotted.module.ClassName")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"class {class_name!r} not found in module {module_path!r}")
    return cls


def strategy_underlyings(strategies_dir: Path) -> set[str]:
    """Underlyings every loaded strategy's ``params.underlying`` declares.

    Single source of truth for "which underlyings does live trading need
    options/chain data for" -- derived from the strategy configs themselves
    rather than a hand-maintained global settings list. Adding a new strategy YAML is the
    only step needed to bring its underlying's chain/warehouse online; a
    strategy that no longer needs one drops off automatically when its YAML
    is removed or edited. Read at process start by the options poller and the
    standalone warehouse service -- both filter this against their own
    supported-underlying registry, so an unrecognised value here is simply
    not requested rather than raising.
    """
    underlyings: set[str] = set()
    for cfg in load_all(strategies_dir):
        u = cfg.params.get("underlying")
        if u:
            underlyings.add(str(u))
    return underlyings


def get_strategy(
    strategy_id: str, strategies_dir: Path = Path("strategies")
) -> Strategy:
    """Load a strategy's YAML config and return an instantiated Strategy.

    Used outside the live host (e.g. the backtest CLI) to get a ready-to-run instance
    with ``strategy_id`` and ``params`` populated, mirroring how StrategyHost.start does it.
    """
    cfg = load_one(strategy_id, strategies_dir)
    cls = import_strategy_class(cfg.cls)
    instance: Strategy = cls()
    instance.strategy_id = cfg.id
    instance.params = dict(cfg.params)
    return instance
