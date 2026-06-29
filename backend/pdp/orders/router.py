from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.broker_sync.models import BrokerFund
from pdp.instruments.models import Instrument
from pdp.orders.models import Order, OrderStatus, PreflightResult, TradeMode
from pdp.orders.paper import ChargesCalculator, compute_charges

if TYPE_CHECKING:
    from pdp.orders.dhan_broker import DhanBroker
    from pdp.orders.margin import MarginService, OrderSpec
    from pdp.orders.paper import PaperBroker
    from pdp.risk.feed_halt import FeedStaleHalt
    from pdp.settings import Settings

log = structlog.get_logger()


def _check_lot_freeze(
    qty: int,
    lot_size: int,
    freeze_qty: int | None,
    freeze_qty_by_underlying: dict[str, int],
    security_id: str,
    exchange_segment: str,
) -> list[str]:
    """Pure lot/freeze validator; returns a list of violation strings (empty = pass).

    Called only when an instrument row exists. Extracted from _preflight so it can
    be unit-tested without a DB session.
    """
    violations: list[str] = []
    if lot_size > 1 and qty % lot_size != 0:
        violations.append(f"qty {qty} not a multiple of lot_size {lot_size}")
    effective_freeze = freeze_qty
    if effective_freeze is None:
        for underlying, fz in freeze_qty_by_underlying.items():
            if underlying in (security_id + exchange_segment).upper():
                effective_freeze = fz
                break
    if effective_freeze is not None and qty > effective_freeze:
        violations.append(f"qty {qty} exceeds exchange freeze limit {effective_freeze}")
    return violations


def select_broker(settings: Settings) -> tuple[str, str]:
    """Return (broker_name, mode) based on settings.  v1 always returns paper."""
    if settings.LIVE and settings.BROKER == "dhan" and settings.DHAN_CLIENT_ID:
        return ("dhan", TradeMode.LIVE)
    return ("paper", TradeMode.PAPER)


class OrderRouter:
    """
    Validates, persists, and routes order placement requests.

    Handles:
    - Idempotency via client_order_id UNIQUE constraint
    - Lot-size + freeze-qty validation against instruments table
    - Pre-flight margin check (live Dhan API, gated by MARGIN_CHECK_ENABLED)
    - Pre-trade charge estimate (reuses ChargesCalculator)
    - Broker selection (paper unless LIVE=1 + BROKER=dhan + creds)
    - Handing filled orders to PaperBroker / DhanBroker
    """

    def __init__(
        self,
        settings: Settings,
        paper: PaperBroker,
        dhan_broker: DhanBroker | None = None,
        margin_service: MarginService | None = None,
        feed_halt: FeedStaleHalt | None = None,
    ) -> None:
        self._settings = settings
        self._paper = paper
        self._dhan = dhan_broker
        self._margin = margin_service
        self._feed_halt = feed_halt

    def _broker_for(self, broker: str) -> PaperBroker | DhanBroker:
        """Select the engine that owns orders for the given broker name."""
        if broker == "dhan" and self._dhan is not None:
            return self._dhan
        return self._paper

    async def place_order(
        self,
        session: AsyncSession,
        *,
        client_order_id: str | None,
        security_id: str,
        exchange_segment: str,
        side: str,
        qty: int,
        order_type: str,
        price: Decimal | None,
        trigger_price: Decimal | None,
        product: str,
        strategy_id: str | None,
    ) -> Order:
        broker, mode = select_broker(self._settings)

        # Feed-stale safe-halt: block new live entries if sustained staleness engaged.
        # Paper orders are unaffected (no real money at risk).
        if mode == TradeMode.LIVE and self._feed_halt is not None and self._feed_halt.live_blocked:
            log.warning(
                "order_blocked_feed_stale_halt",
                security_id=security_id,
                mode=mode,
            )
            if client_order_id:
                existing = await self._find_by_client_id(session, client_order_id)
                if existing is not None:
                    return existing
            order = Order(
                client_order_id=client_order_id,
                broker=broker,
                mode=mode,
                security_id=security_id,
                exchange_segment=exchange_segment,
                side=side,
                qty=qty,
                order_type=order_type,
                price=price,
                trigger_price=trigger_price,
                product=product,
                status=OrderStatus.REJECTED,
                placed_at=datetime.now(UTC),
                reject_reason="feed_stale_halt: live entries blocked until operator clears",
                strategy_id=strategy_id,
            )
            session.add(order)
            await session.flush()
            await session.commit()
            await session.refresh(order)
            return order

        # Idempotency: return existing order if client_order_id already exists
        if client_order_id:
            existing = await self._find_by_client_id(session, client_order_id)
            if existing is not None:
                return existing

        # Pre-flight: lot/freeze validation + charge estimate + margin check
        reject_reason: str | None = None
        if self._settings.ORDER_PREFLIGHT_ENABLED:
            pf = await self._preflight(
                session,
                security_id=security_id,
                exchange_segment=exchange_segment,
                side=side,
                qty=qty,
                price=price or Decimal("0"),
                product=product,
                mode=mode,
            )
            if not pf.ok:
                reject_reason = "; ".join(pf.violations)
                if mode == TradeMode.PAPER:
                    # advisory in paper — log but don't block
                    log.warning(
                        "order_preflight_advisory",
                        security_id=security_id,
                        violations=pf.violations,
                    )
                    reject_reason = None
        else:
            # Fallback: basic lot-size check (pre-existing behaviour)
            reject_reason = await self._validate_lot_size(session, security_id, exchange_segment, qty)

        status = OrderStatus.REJECTED if reject_reason else OrderStatus.OPEN

        order = Order(
            client_order_id=client_order_id,
            broker=broker,
            mode=mode,
            security_id=security_id,
            exchange_segment=exchange_segment,
            side=side,
            qty=qty,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            product=product,
            status=status,
            placed_at=datetime.now(UTC),
            reject_reason=reject_reason,
            strategy_id=strategy_id,
        )
        session.add(order)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            existing = await self._find_by_client_id(session, client_order_id)
            if existing is not None:
                return existing
            raise

        await session.commit()
        await session.refresh(order)

        if status == OrderStatus.OPEN:
            await self._broker_for(broker).add_order(order)
            log.info(
                "order_placed",
                order_id=order.id,
                broker=broker,
                security_id=security_id,
                order_type=order_type,
            )
        else:
            log.info("order_rejected", order_id=order.id, reason=reject_reason)

        return order

    async def cancel_order(self, session: AsyncSession, order_id: int) -> Order | None:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None:
            return None
        if order.status not in (OrderStatus.NEW, OrderStatus.OPEN):
            return order  # already terminal — return as-is
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(UTC)
        await session.commit()
        await self._broker_for(order.broker).cancel_order(order_id)
        return order

    async def cancel_open_entry_orders(
        self,
        session: AsyncSession,
        security_id: str,
        strategy_id: str,
    ) -> list[int]:
        """Cancel all OPEN SELL orders for a security+strategy before a close event.

        Returns the list of cancelled order IDs.
        """
        broker, _ = select_broker(self._settings)
        result = await session.execute(
            select(Order).where(
                Order.security_id == security_id,
                Order.strategy_id == strategy_id,
                Order.side == "SELL",
                Order.status == OrderStatus.OPEN,
            )
        )
        orders = result.scalars().all()
        now = datetime.now(UTC)
        cancelled_ids: list[int] = []
        for order in orders:
            order.status = OrderStatus.CANCELLED
            order.cancelled_at = now
            cancelled_ids.append(order.id)
        if cancelled_ids:
            await session.commit()
            for oid in cancelled_ids:
                await self._broker_for(broker).cancel_order(oid)
            log.info("entry_orders_cancelled", count=len(cancelled_ids), security_id=security_id)
        return cancelled_ids

    async def _preflight(
        self,
        session: AsyncSession,
        *,
        security_id: str,
        exchange_segment: str,
        side: str,
        qty: int,
        price: Decimal,
        product: str,
        mode: str,
    ) -> PreflightResult:
        result = PreflightResult()
        s = self._settings

        # 1. Lot-size + freeze-qty validation
        inst_row = await session.execute(
            select(Instrument.lot_size, Instrument.freeze_qty).where(
                Instrument.security_id == security_id,
                Instrument.exchange_segment == exchange_segment,
            )
        )
        row = inst_row.first()
        if row is not None:
            lot_size, freeze_qty = row
            result.violations.extend(
                _check_lot_freeze(
                    qty, lot_size, freeze_qty,
                    s.FREEZE_QTY_BY_UNDERLYING, security_id, exchange_segment,
                )
            )

        # 2. Charge estimate (reuses PaperBroker's ChargesCalculator; no new cost model)
        if self._paper._costs:
            dummy_order = type("_O", (), {
                "exchange_segment": exchange_segment,
                "side": side,
                "qty": qty,
            })()
            result.charge_estimate = compute_charges(
                self._paper._costs, dummy_order, price or Decimal("1"), qty=qty
            )

        # 3. Margin check — live Dhan API, credential-gated
        if (
            s.MARGIN_CHECK_ENABLED
            and self._margin is not None
            and mode == TradeMode.LIVE
        ):
            try:
                from pdp.orders.margin import OrderSpec

                spec = OrderSpec(
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    transaction_type=side,
                    quantity=qty,
                    price=price,
                    product=product,
                )
                required = await self._margin.required_margin([spec])
                result.margin_required = required

                # Read available balance from PG (last broker_sync run)
                fund_row = await session.execute(
                    select(BrokerFund.available_balance).where(
                        BrokerFund.account_id == s.DHAN_CLIENT_ID
                    )
                )
                fund = fund_row.scalar_one_or_none()
                available = fund or Decimal("0")
                result.margin_available = available

                threshold = available * (1 - Decimal(str(s.MARGIN_BUFFER_PCT)) / 100)
                if required > threshold:
                    result.violations.append(
                        f"insufficient margin: required {required:.2f} > "
                        f"available {available:.2f} (buffer {s.MARGIN_BUFFER_PCT}%)"
                    )
            except Exception as exc:
                if s.MARGIN_FAILOPEN:
                    log.warning("margin_check_failed_open", exc=str(exc))
                else:
                    result.violations.append(f"margin check error (fail-closed): {exc}")

        if result.violations:
            result.ok = False
            log.info(
                "order_preflight_failed",
                security_id=security_id,
                violations=result.violations,
                charge_estimate=str(result.charge_estimate),
            )
        else:
            log.debug(
                "order_preflight_ok",
                security_id=security_id,
                charge_estimate=str(result.charge_estimate),
                margin_required=str(result.margin_required),
            )
        return result

    async def _validate_lot_size(
        self,
        session: AsyncSession,
        security_id: str,
        exchange_segment: str,
        qty: int,
    ) -> str | None:
        result = await session.execute(
            select(Instrument.lot_size).where(
                Instrument.security_id == security_id,
                Instrument.exchange_segment == exchange_segment,
            )
        )
        row = result.first()
        if row is None:
            return None  # unknown instrument — allow, broker handles it
        lot_size: int = row[0]
        if lot_size > 1 and qty % lot_size != 0:
            return f"qty not multiple of lot_size ({lot_size})"
        return None

    async def _find_by_client_id(self, session: AsyncSession, client_order_id: str) -> Order | None:
        result = await session.execute(
            select(Order).where(Order.client_order_id == client_order_id)
        )
        return result.scalar_one_or_none()
