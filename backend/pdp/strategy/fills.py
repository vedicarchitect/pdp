"""Shared entry-fill resolution and orphan-fill recovery for option-selling strategies.

These four helpers encode a correctness rule learned from live incidents, not a
convenience: **an unresolved entry price must never silently discard a real fill.**
A strategy that gives up on a leg whose price it could not read, without first proving
the order was actually cancelled, leaves an untracked broker position behind.

They live here — rather than on a strategy class — because duplicating them is exactly
what went wrong before: ``directional_strangle``'s ``_open_short`` carried the
cancel-confirmation fix while ``_open_hedge``/``_open_momentum`` did not, leaving the
same race open in two of three entry paths until a review caught it
(``strangle-orphan-fill-reconciliation``, 2026-07-25). One implementation, called by
every entry path of every strategy, is the structural fix.

Each function takes the ``StrategyContext`` and the caller's own LTP cache explicitly,
so there is no hidden coupling to a particular strategy class.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdp.strategy.context import StrategyContext

__all__ = [
    "await_fill_avg_px",
    "await_option_ltp",
    "confirm_fill_or_recover",
    "resolve_fill_price",
]

# Broker-average poll schedule: 8 attempts at 150ms, then one final read.
_BROKER_POLL_ATTEMPTS = 8
_BROKER_POLL_INTERVAL_S = 0.15
_LTP_POLL_INTERVAL_S = 0.2


async def await_option_ltp(
    ctx: StrategyContext, ltp_cache: dict[str, float], sid: str, timeout_s: float
) -> bool:
    """Wait up to *timeout_s* for a freshly-subscribed option's first LTP.

    Returns True once a positive LTP is visible (in-process cache or market feed), so a
    subsequent MARKET order fills on the first tick rather than aborting cold. Returns
    False if no tick arrives within the budget — the caller still attempts the open, and
    the fill-price fallbacks plus the abort path handle a genuinely cold leg.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        cached = ltp_cache.get(sid)
        if cached and cached > 0:
            return True
        if ctx.market is not None:
            ltp, _ = await ctx.market.ltp_with_age(sid)
            if ltp and ltp > 0:
                return True
        await asyncio.sleep(_LTP_POLL_INTERVAL_S)
    return False


async def resolve_fill_price(
    ctx: StrategyContext, ltp_cache: dict[str, float], sid: str
) -> Decimal | None:
    """Resolve a real fill reference price through three fallback layers.

    1. Broker position average (PaperBroker / DhanBroker), polled briefly.
    2. The caller's in-process LTP cache.
    3. The market feed's Redis LTP.

    Returns ``None`` only when every layer is cold. Callers MUST treat ``None`` as
    "abort the leg", never as "record entry_price=0" — a zero entry price makes MTM
    compute as ``-ltp x qty``, a phantom loss that has previously tripped a day-loss cap.
    """
    for _ in range(_BROKER_POLL_ATTEMPTS):
        _, avg_px = await ctx.orders.get_position(sid)
        if avg_px and avg_px > 0:
            return avg_px
        await asyncio.sleep(_BROKER_POLL_INTERVAL_S)
    _, avg_px = await ctx.orders.get_position(sid)
    if avg_px and avg_px > 0:
        return avg_px

    ltp_cached = ltp_cache.get(sid)
    if ltp_cached and ltp_cached > 0:
        ctx.log.warning("fill_avg_px_ltp_fallback", sid=sid, source="ltp_cache", ltp=ltp_cached)
        return Decimal(str(ltp_cached))

    if ctx.market is not None:
        ltp_feed, _ = await ctx.market.ltp_with_age(sid)
        if ltp_feed and ltp_feed > 0:
            ctx.log.warning(
                "fill_avg_px_ltp_fallback", sid=sid, source="market_feed", ltp=float(ltp_feed)
            )
            return Decimal(str(ltp_feed))

    ctx.log.warning("fill_avg_px_zero", sid=sid)
    return None


async def await_fill_avg_px(
    ctx: StrategyContext, ltp_cache: dict[str, float], sid: str
) -> Decimal | None:
    """Poll the broker until filled, then fall through to :func:`resolve_fill_price`."""
    return await resolve_fill_price(ctx, ltp_cache, sid)


async def confirm_fill_or_recover(
    ctx: StrategyContext, sid: str, order: Any
) -> Decimal | None:
    """Before discarding an entry leg whose fill price did not resolve, prove the order
    was actually cancelled.

    If the cancel did **not** take effect — the order had already filled, or filled
    concurrently with the cancel (e.g. during a tick backpressure/drop event) — the
    position is real and MUST be tracked rather than orphaned, so its true fill price is
    taken from the broker.

    Deliberately checks only the broker's own recorded position average, never an LTP
    estimate: :func:`resolve_fill_price` already exhausted the LTP layers before this was
    called, so falling back to them again would accept "a price exists" as proof of a
    fill that may not have happened (a REJECTED order, or one cancelled by another path
    just before this check), registering a phantom leg with no broker position behind it.
    """
    cancelled_ids = await ctx.orders.cancel_open_entry_orders(sid)
    if order.id in cancelled_ids:
        return None
    _, avg_px = await ctx.orders.get_position(sid)
    if avg_px and avg_px > 0:
        ctx.log.warning(
            "entry_order_filled_after_abort", sid=sid, order_id=order.id, avg_px=str(avg_px)
        )
        return avg_px
    return None
