"""Event model + enums for the live event publisher."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any


def _empty_payload() -> dict[str, Any]:
    return {}


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}[self.value]


class EventType(StrEnum):
    # A. price levels & confluence
    PRICE_LEVEL_CROSS = "PRICE_LEVEL_CROSS"
    LEVEL_PROXIMITY = "LEVEL_PROXIMITY"
    CAMARILLA_TOUCH = "CAMARILLA_TOUCH"
    CONFLUENCE_ZONE = "CONFLUENCE_ZONE"
    # B. trend / momentum
    EMA_CROSS = "EMA_CROSS"
    PRICE_EMA_CROSS = "PRICE_EMA_CROSS"
    SUPERTREND_FLIP = "SUPERTREND_FLIP"
    PSAR_FLIP = "PSAR_FLIP"
    MACD_CROSS = "MACD_CROSS"
    ELDER_IMPULSE_CHANGE = "ELDER_IMPULSE_CHANGE"
    ELLIOTT_WAVE = "ELLIOTT_WAVE"
    ML_SIGNAL_FLIP = "ML_SIGNAL_FLIP"
    RSI_EXTREME = "RSI_EXTREME"
    # C. range / breakout / volume
    LEVEL_BREAK = "LEVEL_BREAK"
    CUSTOM_RANGE_BREAK = "CUSTOM_RANGE_BREAK"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    VOLUME_SR = "VOLUME_SR"
    GAP_OPEN = "GAP_OPEN"
    # D. options / OI / greeks
    OI_WALL = "OI_WALL"
    OI_BUILDUP = "OI_BUILDUP"
    OI_VOLUME_SPIKE = "OI_VOLUME_SPIKE"
    PCR_SHIFT = "PCR_SHIFT"
    GEX_WALL = "GEX_WALL"
    MAX_PAIN_PIN = "MAX_PAIN_PIN"
    IV_SHIFT = "IV_SHIFT"
    DELTA_NEUTRAL_DRIFT = "DELTA_NEUTRAL_DRIFT"
    BREAKEVEN_BREACH = "BREAKEVEN_BREACH"
    EXPIRY_COUNTDOWN = "EXPIRY_COUNTDOWN"
    # E. position / P&L / portfolio
    MTM_SWING = "MTM_SWING"
    OTM_DISTANCE = "OTM_DISTANCE"
    SAFE_TO_EXIT_TRAIL = "SAFE_TO_EXIT_TRAIL"
    SAFE_TO_EXIT_MOMENTUM = "SAFE_TO_EXIT_MOMENTUM"
    LEG_STOP_PROXIMITY = "LEG_STOP_PROXIMITY"
    DIRECTIONAL_JUNCTION = "DIRECTIONAL_JUNCTION"
    PORTFOLIO_STATS = "PORTFOLIO_STATS"
    POSITION_CHANGE = "POSITION_CHANGE"
    # F. system / order events
    ORDER_FILL = "ORDER_FILL"
    SL_HIT = "SL_HIT"
    TARGET_HIT = "TARGET_HIT"
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
    MARGIN_WARNING = "MARGIN_WARNING"
    STRATEGY_SIGNAL = "STRATEGY_SIGNAL"
    WARMUP_INCOMPLETE = "WARMUP_INCOMPLETE"
    MISSING_LTP = "MISSING_LTP"
    NAKED_POSITION = "NAKED_POSITION"
    FEED_STALE = "FEED_STALE"
    INDICATOR_UNSEEDED = "INDICATOR_UNSEEDED"
    EXCEPTION_CRITICAL = "EXCEPTION_CRITICAL"
    POSITION_RECONCILE_MISMATCH = "POSITION_RECONCILE_MISMATCH"
    VIX_SPIKE = "VIX_SPIKE"
    CLOSE_UNPRICED = "CLOSE_UNPRICED"
    POSITION_SIZE_CAPPED = "POSITION_SIZE_CAPPED"


@dataclass(slots=True)
class Event:
    """A single monitoring event ready for delivery + persistence."""

    event_type: EventType
    severity: Severity
    security_id: str
    title: str
    message: str
    underlying: str | None = None
    timeframe: str | None = None
    payload: dict[str, Any] = field(default_factory=_empty_payload)
    # dedup_key groups recurrences of the *same* condition (see EventService cooldown).
    dedup_key: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "security_id": self.security_id,
            "underlying": self.underlying,
            "timeframe": self.timeframe,
            "title": self.title,
            "message": self.message,
            "payload": self.payload,
            "ts": self.ts.isoformat(),
        }

    def to_mongo(self) -> dict[str, Any]:
        d = self.to_dict()
        d["ts"] = self.ts  # store native datetime so the TTL index applies
        d["dedup_key"] = self.dedup_key
        return d

    @property
    def ist_str(self) -> str:
        """IST-rendered timestamp (user preference: all timestamps in IST)."""
        return (self.ts + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S IST")


@dataclass(slots=True)
class MonitoredPosition:
    """One open leg of a manual Dhan position under monitoring."""

    security_id: str
    underlying: str
    exchange_segment: str
    net_qty: int
    avg_price: float
    side: str  # "LONG" | "SHORT"
    strike: float | None = None
    option_type: str | None = None  # "CE" | "PE" | None (futures/equity)
    expiry: str | None = None
    delta: float | None = None
    trading_symbol: str | None = None
    # Running mark-to-market peak for trailing safe-to-exit.
    mtm_peak: float = 0.0
    last_mtm: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.security_id}:{self.exchange_segment}"

    @property
    def is_option(self) -> bool:
        return self.option_type in ("CE", "PE")
