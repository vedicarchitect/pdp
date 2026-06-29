"""Dhan margin pre-check for order preflight.

Routes single-leg orders to /margincalculator and multi-leg baskets to
/margincalculator/multi.  Dhan returns HTTP 200 even on errors; the
_normalise_success_response guard converts those into failures.  Response
keys may be snake_case or camelCase depending on SDK version.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog

log = structlog.get_logger()


def _normalise_success_response(resp: Any) -> dict[str, Any]:
    """Raise on a Dhan HTTP-200 envelope that carries an error payload."""
    if not isinstance(resp, dict):
        raise ValueError(f"unexpected margin response type: {type(resp)}")
    status = resp.get("status") or resp.get("Status")
    if status and str(status).lower() == "failure":
        err_type = resp.get("errorType") or resp.get("error_type") or "unknown"
        err_msg = resp.get("errorMessage") or resp.get("error_message") or str(resp)
        raise ValueError(f"Dhan margin API error [{err_type}]: {err_msg}")
    return resp


def _pick(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first matching key from a dict (snake or camel)."""
    for k in keys:
        if k in d:
            return d[k]
    return default


@dataclass
class MarginResult:
    required: Decimal = Decimal("0")
    available: Decimal = Decimal("0")
    ok: bool = True
    advisory: str = ""


@dataclass
class OrderSpec:
    """Minimal description of one order leg for margin calculation."""
    security_id: str
    exchange_segment: str
    transaction_type: str   # "BUY" or "SELL"
    quantity: int
    price: Decimal
    product: str            # Dhan product type e.g. "MARGIN", "INTRADAY"
    order_type: str = "LIMIT"


class MarginService:
    """Async wrapper around Dhan's margin calculator endpoints."""

    def __init__(self, client_id: str, access_token: str) -> None:
        self._client_id = client_id
        self._access_token = access_token
        self._client: Any = None

    @classmethod
    def from_settings(cls, settings: Any) -> "MarginService | None":
        """Return None when credentials are absent (mirrors DhanBroker gate)."""
        if not (settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN):
            return None
        return cls(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)

    def _ensure_client(self) -> Any:
        if self._client is None:
            from dhanhq import DhanContext, dhanhq
            self._client = dhanhq(DhanContext(self._client_id, self._access_token))
        return self._client

    async def required_margin(self, orders: list[OrderSpec]) -> Decimal:
        """Return total required margin for one or more order legs (INR)."""
        if not orders:
            return Decimal("0")
        if len(orders) == 1:
            return await self._single_margin(orders[0])
        return await self._basket_margin(orders)

    async def _single_margin(self, order: OrderSpec) -> Decimal:
        def _call() -> Any:
            client = self._ensure_client()
            return client.margin_calculator(
                security_id=order.security_id,
                exchange_segment=order.exchange_segment,
                transaction_type=order.transaction_type,
                quantity=order.quantity,
                price=float(order.price),
                product_type=order.product,
                order_type=order.order_type,
            )

        resp = await asyncio.to_thread(_call)
        data = _normalise_success_response(resp)
        raw = _pick(data, "totalMargin", "total_margin", "data", default=0)
        if isinstance(raw, dict):
            raw = _pick(raw, "totalMargin", "total_margin", default=0)
        return Decimal(str(raw or 0))

    async def _basket_margin(self, orders: list[OrderSpec]) -> Decimal:
        legs = [
            {
                "security_id": o.security_id,
                "exchange_segment": o.exchange_segment,
                "transaction_type": o.transaction_type,
                "quantity": o.quantity,
                "price": float(o.price),
                "product_type": o.product,
                "order_type": o.order_type,
            }
            for o in orders
        ]

        def _call() -> Any:
            client = self._ensure_client()
            return client.margin_calculator_basket(orders=legs)

        resp = await asyncio.to_thread(_call)
        data = _normalise_success_response(resp)
        return _parse_basket_margin_response(data)


def _parse_basket_margin_response(data: dict[str, Any]) -> Decimal:
    """Extract total required margin; handles snake_case and camelCase."""
    total = _pick(data, "totalMargin", "total_margin", default=None)
    if total is not None:
        return Decimal(str(total))
    inner = _pick(data, "data", default=None)
    if isinstance(inner, dict):
        total = _pick(inner, "totalMargin", "total_margin", default=0)
        return Decimal(str(total))
    if isinstance(inner, list) and inner:
        acc = Decimal("0")
        for item in inner:
            if isinstance(item, dict):
                v = _pick(item, "totalMargin", "total_margin", "margin", default=0)
                acc += Decimal(str(v or 0))
        return acc
    return Decimal("0")
