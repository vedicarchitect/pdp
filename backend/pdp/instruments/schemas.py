from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    security_id: str
    exchange_segment: str
    trading_symbol: str
    instrument_type: str
    underlying: str | None = None
    expiry: date | None = None
    strike: Decimal | None = None
    option_type: str | None = None
    lot_size: int
    tick_size: Decimal
    isin: str | None = None
    updated_at: datetime
