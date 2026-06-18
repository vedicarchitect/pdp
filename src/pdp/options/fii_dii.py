from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass
class FIIDIIData:
    date: date
    fii_index_futures_net: float
    fii_index_options_net: float
    fii_stock_futures_net: float
    dii_index_futures_net: float
    dii_index_options_net: float
    dii_stock_futures_net: float

class FIIDIISource(Protocol):
    async def fetch(self, d: date) -> FIIDIIData | None: ...

class StubFIIDIISource:
    async def fetch(self, d: date) -> FIIDIIData | None:
        return None  # No data available
