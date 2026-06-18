from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class StrikeSelection(BaseModel):
    method: Literal["atm_offset", "by_premium", "by_delta"] = "atm_offset"
    offset: int = 0
    target_premium: float | None = None
    target_delta: float | None = None


class LegConfig(BaseModel):
    type: Literal["CE", "PE"]
    side: Literal["BUY", "SELL"]
    lots: int = 1
    strike_selection: StrikeSelection = Field(default_factory=StrikeSelection)


class SLTargetSpec(BaseModel):
    type: Literal["points", "percent"] = "points"
    value: float


class TrailingSlConfig(BaseModel):
    enabled: bool = False
    trail_after: float = 20.0
    trail_step: float = 5.0


class ReEntryConfig(BaseModel):
    enabled: bool = False
    max_count: int = 2


class RiskConfig(BaseModel):
    combined_sl: SLTargetSpec | None = None
    combined_target: SLTargetSpec | None = None
    per_leg_sl: SLTargetSpec | None = None
    trailing_sl: TrailingSlConfig = Field(default_factory=TrailingSlConfig)
    re_entry: ReEntryConfig = Field(default_factory=ReEntryConfig)


class EntryConfig(BaseModel):
    time_ist: str
    legs: list[LegConfig]


class ExitConfig(BaseModel):
    time_ist: str


class DateRange(BaseModel):
    from_: date = Field(alias="from")
    to: date

    model_config = {"populate_by_name": True}


class OptionsStrategyConfig(BaseModel):
    type: Literal["options-strategy"] = "options-strategy"
    name: str
    underlying: str = "NIFTY"
    date_range: DateRange
    expiry_selection: Literal["weekly", "monthly", "nearest"] = "weekly"
    entry: EntryConfig
    exit: ExitConfig
    risk: RiskConfig = Field(default_factory=RiskConfig)
    lot_size: int = 75
    commissions: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path) -> OptionsStrategyConfig:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
