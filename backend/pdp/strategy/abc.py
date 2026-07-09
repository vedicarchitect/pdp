from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed
    from pdp.market.models import Tick
    from pdp.strategy.context import StrategyContext
    from pdp.strategy.log import StrategyDailyLog

_IST = ZoneInfo("Asia/Kolkata")


@dataclass(slots=True)
class FillEvent:
    order_id: int
    security_id: str
    exchange_segment: str
    side: str
    qty: int
    fill_price: Decimal
    charges: Decimal
    filled_at: datetime
    strategy_id: str | None = None


class Strategy(ABC):
    """Base class for all user-defined strategies.

    Subclasses MUST implement ``on_init``. All other hooks are optional no-ops.
    The host sets ``strategy_id``, ``params``, ``_mode``, and ``_slog`` before
    calling ``on_init``.
    """

    strategy_id: str = ""
    params: dict = {}  # noqa: RUF012
    _mode: str = "paper"  # "paper" | "live"; set by host from settings
    _slog: StrategyDailyLog | None = None  # set by host; None → logging is a no-op
    _disarmed: bool = False  # set by host; True → ignore events

    @abstractmethod
    async def on_init(self, ctx: StrategyContext) -> None:
        """Called once before the first event is delivered. Store ``ctx`` here."""

    async def on_tick(self, tick: Tick) -> None:
        pass

    async def on_bar(self, bar: BarClosed) -> None:
        pass

    async def on_fill(self, fill: FillEvent) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    # ------------------------------------------------------------------ #
    # Strategy log                                                         #
    # ------------------------------------------------------------------ #

    def log_config_header(
        self,
        *,
        mode: str,
        timeframe: str,
        params: dict[str, Any],
        watchlist: list[Any],
    ) -> None:
        """Emit the run-start config header once at the beginning of each run."""
        if self._slog is None:
            return
        self._slog.write(
            {
                "event": "run_start",
                "strategy_id": self.strategy_id,
                "mode": mode,
                "timeframe": timeframe,
                "params": params,
                "watchlist": watchlist,
                "ts": datetime.now(tz=_IST).isoformat(),
            }
        )

    def log_decision(self, action: str, reason: str, **fields: Any) -> None:
        """Log a trading decision (open / scale / flip / leg_stop / day_stop / …)."""
        if self._slog is None:
            return
        self._slog.write(
            {
                "event": "decision",
                "strategy_id": self.strategy_id,
                "action": action,
                "reason": reason,
                **fields,
                "ts": datetime.now(tz=_IST).isoformat(),
            }
        )

    def log_heartbeat(self, bar_time: datetime | None = None) -> None:
        """Emit a periodic state snapshot; call once per bar within the trading window."""
        if self._slog is None:
            return
        record: dict[str, Any] = {
            "event": "heartbeat",
            "strategy_id": self.strategy_id,
            "mode": self._mode,
            "ts": datetime.now(tz=_IST).isoformat(),
        }
        if bar_time is not None:
            record["bar_time"] = bar_time.isoformat()
        record.update(self.heartbeat_fields())
        self._slog.write(record)

    def heartbeat_fields(self) -> dict[str, Any]:
        """Strategy-specific heartbeat fields; override to add ST state, P&L, stops, …"""
        return {}
