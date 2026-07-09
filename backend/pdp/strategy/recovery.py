"""Crash-recovery helper for SuperTrend strategies.

Queries the ledger on startup to rebuild in-memory state after a process restart.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select

if TYPE_CHECKING:
    from pdp.strategy.context import StrategyContext

log = structlog.get_logger()
_IST = ZoneInfo("Asia/Kolkata")


async def recover_strategy_state(
    ctx: StrategyContext,
    strategy_id: str,
    lot_size: int,
    today_ist: date,
) -> tuple[dict[str, Any] | None, dict[str, Decimal]]:
    """Recover open-leg state and day baseline from the ledger on strategy restart.

    Returns ``(recovered_current, day_baseline)``.
    ``recovered_current`` mirrors the shape of ``SuperTrendShort._current``, or
    ``None`` when the strategy is flat or recovery is skipped.
    ``day_baseline`` is ``{security_id: realized_pnl}`` used as ``_day_baseline`` seed.
    """
    day_baseline = await ctx.orders.get_realized_pnl_per_security()
    positions = await ctx.orders.get_positions()

    shorts = [p for p in positions if p.net_qty < 0]
    if not shorts:
        return None, day_baseline

    if len(shorts) > 1:
        log.warning("recovery_multiple_shorts", count=len(shorts), strategy_id=strategy_id)

    pos = max(shorts, key=lambda p: p.id)

    if ctx.session_maker is None:
        log.warning("recovery_no_session_maker", strategy_id=strategy_id)
        return None, day_baseline

    async with ctx.session_maker() as session:
        from pdp.instruments.models import Instrument
        from pdp.orders.models import Order as OrderModel
        from pdp.orders.models import Trade

        # Cross-day guard: last fill date for this strategy + security.
        result = await session.execute(
            select(Trade.filled_at)
            .join(OrderModel, Trade.order_id == OrderModel.id)
            .where(
                OrderModel.strategy_id == strategy_id,
                Trade.security_id == pos.security_id,
            )
            .order_by(Trade.filled_at.desc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            log.warning("recovery_no_fills_found", security_id=pos.security_id)
            return None, day_baseline

        last_fill_date = row[0].astimezone(_IST).date()
        if last_fill_date != today_ist:
            log.warning(
                "recovery_cross_day_stale",
                security_id=pos.security_id,
                last_fill_date=str(last_fill_date),
                today_ist=str(today_ist),
            )
            return None, day_baseline

        result = await session.execute(
            select(Instrument).where(
                Instrument.security_id == pos.security_id,
                Instrument.exchange_segment == pos.exchange_segment,
            )
        )
        inst = result.scalar_one_or_none()

    if inst is None:
        log.warning("recovery_instrument_not_found", security_id=pos.security_id)
        return None, day_baseline

    abs_qty = abs(pos.net_qty)
    lots, remainder = divmod(abs_qty, lot_size)
    if remainder != 0:
        log.warning(
            "recovery_qty_not_divisible",
            net_qty=pos.net_qty,
            lot_size=lot_size,
            lots_floored=lots,
        )

    if lots == 0:
        log.warning("recovery_lots_zero", net_qty=pos.net_qty, lot_size=lot_size)
        return None, day_baseline

    recovered_current = {
        "security_id": pos.security_id,
        "segment": pos.exchange_segment,
        "option_type": inst.option_type,
        "strike": inst.strike,
        "lots": lots,
    }

    log.info(
        "state_recovered",
        strategy_id=strategy_id,
        current_security_id=pos.security_id,
        option_type=inst.option_type,
        strike=str(inst.strike),
        lots=lots,
        day_baseline_total=str(sum(day_baseline.values())),
    )

    return recovered_current, day_baseline
