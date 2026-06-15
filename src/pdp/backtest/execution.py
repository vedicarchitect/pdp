from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pdp.backtest.engine import BacktestEngine

log = structlog.get_logger()


@dataclass
class OrderRequest:
    """A request to execute an order during backtest."""

    symbol: str
    quantity: int
    side: str
    order_type: str = "MARKET"
    price: Decimal | None = None


class BacktestExecutor:
    """Simulates order execution during backtest."""

    def __init__(self, engine: BacktestEngine) -> None:
        self.engine = engine
        self.orders: list[OrderRequest] = []

    async def execute_market_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        fill_price: Decimal,
        metadata: dict | None = None,
    ) -> bool:
        """Execute a market order at the given fill price."""
        side_upper = side.upper()

        if side_upper not in ("BUY", "SELL"):
            log.error("invalid_side", side=side)
            return False

        if quantity <= 0:
            log.error("invalid_quantity", quantity=quantity)
            return False

        if fill_price <= 0:
            log.error("invalid_price", price=float(fill_price))
            return False

        success = await self.engine.execute_order(
            symbol=symbol,
            quantity=quantity,
            side=side_upper,
            current_price=fill_price,
            metadata=metadata,
        )

        if success:
            log.info(
                "market_order_executed",
                symbol=symbol,
                side=side_upper,
                quantity=quantity,
                fill_price=float(fill_price),
            )
        else:
            log.warning(
                "market_order_rejected",
                symbol=symbol,
                side=side_upper,
                quantity=quantity,
                fill_price=float(fill_price),
            )

        return success

    async def check_position_limits(
        self,
        symbol: str,
        proposed_quantity: int,
        max_position_size: int = 1000,
    ) -> bool:
        """Validate that order respects position limits."""
        current_position = self.engine.positions.get(symbol)
        current_qty = current_position.quantity if current_position else 0

        if current_qty + proposed_quantity > max_position_size:
            log.warning(
                "position_limit_exceeded",
                symbol=symbol,
                current_qty=current_qty,
                proposed_qty=proposed_quantity,
                limit=max_position_size,
            )
            return False

        return True

    async def calculate_commission(
        self,
        quantity: int,
        fill_price: Decimal,
        commission_pct: Decimal = Decimal("0.05"),
    ) -> Decimal:
        """Calculate commission for an order."""
        notional = Decimal(str(quantity)) * fill_price
        return (notional * commission_pct) / 100
