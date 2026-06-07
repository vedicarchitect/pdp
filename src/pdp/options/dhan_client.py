"""Dhan options chain client.

Thin async wrapper around the dhanhq SDK's ``expiry_list`` and ``option_chain``
calls. Both calls return the raw Dhan v2 payload; callers parse it through
``pdp.options.poller._parse_chain`` so producer and consumers agree on a single
shape.
"""
from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger()

# Underlying symbol -> (security_id, exchange_segment) in the Dhan index segment.
# Source: Dhan instrument table / dhanhq skill reference.
UNDERLYING_MAP: dict[str, tuple[int, str]] = {
    "NIFTY": (13, "IDX_I"),
    "BANKNIFTY": (25, "IDX_I"),
    "FINNIFTY": (27, "IDX_I"),
    "MIDCPNIFTY": (442, "IDX_I"),
    "SENSEX": (51, "IDX_I"),
}


def _resolve(underlying: str) -> tuple[int, str]:
    key = underlying.upper()
    if key not in UNDERLYING_MAP:
        raise ValueError(
            f"Unsupported underlying: {underlying}. Supported: {list(UNDERLYING_MAP)}"
        )
    return UNDERLYING_MAP[key]


def _make_client(client_id: str, access_token: str):  # type: ignore[no-untyped-def]
    try:
        from dhanhq import DhanContext, dhanhq
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError("dhanhq SDK not installed") from exc
    return dhanhq(DhanContext(client_id, access_token))


async def fetch_expiries(
    underlying: str,
    access_token: str,
    client_id: str,
) -> list[str]:
    """Return available expiry dates (ISO ``YYYY-MM-DD``) sorted ascending."""
    security_id, exchange = _resolve(underlying)
    client = _make_client(client_id, access_token)
    response = await asyncio.to_thread(client.expiry_list, security_id, exchange)

    if isinstance(response, dict) and response.get("status") == "success":
        data = response.get("data") or []
        # SDK may return either a bare list or {"data": [...]}.
        if isinstance(data, dict):
            data = data.get("data", [])
        expiries = sorted(str(e) for e in data if e)
        log.debug("dhan_expiries_fetched", underlying=underlying, count=len(expiries))
        return expiries

    log.warning("dhan_expiries_empty", underlying=underlying, response=str(response)[:200])
    return []


async def fetch_chain(
    underlying: str,
    expiry: str,
    access_token: str,
    client_id: str,
    *,
    httpx_client=None,  # kept for call-site compatibility; unused (SDK is sync)
) -> dict:
    """Fetch the option chain for one ISO ``expiry`` of ``underlying``.

    Returns the raw Dhan payload augmented with the requested expiry::

        {"data": {"last_price": ..., "oc": {"<strike>": {"ce": {...}, "pe": {...}}}},
         "expiry": "<ISO>"}

    Returns ``{"data": {}, "expiry": expiry}`` when no data is available.
    """
    security_id, exchange = _resolve(underlying)
    client = _make_client(client_id, access_token)

    log.debug(
        "dhan_chain_request",
        underlying=underlying,
        security_id=security_id,
        exchange=exchange,
        expiry=expiry,
    )
    response = await asyncio.to_thread(
        client.option_chain, security_id, exchange, expiry
    )

    if isinstance(response, dict) and response.get("status") == "success":
        data = response.get("data") or {}
        # The dhanhq SDK wraps the Dhan API envelope, so the real chain
        # ({last_price, oc}) can sit one level deeper under another "data" key.
        if isinstance(data, dict) and "oc" not in data and isinstance(data.get("data"), dict):
            data = data["data"]
        log.debug("dhan_chain_fetched", underlying=underlying, expiry=expiry)
        return {"data": data, "expiry": expiry}

    log.warning(
        "dhan_chain_fetch_failed",
        underlying=underlying,
        expiry=expiry,
        response=str(response)[:200],
    )
    return {"data": {}, "expiry": expiry}
