from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class CLIConfig:
    live_mode: bool
    default_symbol: str

    @staticmethod
    def from_env() -> CLIConfig:
        live_mode = os.getenv("LIVE", "0").lower() in ("1", "true", "yes")
        default_symbol = os.getenv("DEFAULT_SYMBOL", "NIFTY")
        return CLIConfig(live_mode=live_mode, default_symbol=default_symbol)
