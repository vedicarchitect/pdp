from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed
    from pdp.market.models import Tick
    from pdp.strategy.context import StrategyContext


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
    The host sets ``strategy_id`` and ``params`` before calling ``on_init``.
    """

    strategy_id: str = ""
    params: dict = {}  # noqa: RUF012

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
