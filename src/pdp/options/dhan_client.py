"""Dhan options chain REST client."""
from __future__ import annotations

import structlog

log = structlog.get_logger()

_DHAN_CHAIN_URL = "https://api.dhan.co/v2/optionchain"

# Dhan security IDs for index underlyings
_UNDERLYING_SECURITY_ID: dict[str, str] = {
    "NIFTY": "13",
    "BANKNIFTY": "25",
    "SENSEX": "51",
    "MIDCPNIFTY": "442",
}

_UNDERLYING_EXCHANGE: dict[str, str] = {
    "NIFTY": "NSE",
    "BANKNIFTY": "NSE",
    "SENSEX": "BSE",
    "MIDCPNIFTY": "NSE",
}


async def fetch_chain(
    underlying: str,
    access_token: str,
    client_id: str,
    *,
    httpx_client,  # httpx.AsyncClient injected to avoid import at module level
) -> dict:
    """Fetch the full options chain for an underlying from Dhan.

    Returns the raw JSON response dict or raises on HTTP error.
    """
    security_id = _UNDERLYING_SECURITY_ID.get(underlying.upper())
    exchange = _UNDERLYING_EXCHANGE.get(underlying.upper(), "NSE")
    if not security_id:
        raise ValueError(f"Unknown underlying: {underlying}")

    headers = {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json",
    }
    payload = {
        "UnderlyingScrip": int(security_id),
        "UnderlyingSeg": f"IDX_{exchange}",
    }
    resp = await httpx_client.post(_DHAN_CHAIN_URL, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    log.debug("dhan_chain_fetched", underlying=underlying, status=resp.status_code)
    return data
