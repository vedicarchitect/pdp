"""Shared FastAPI dependencies for the PDP API.

Each function/class does exactly one thing so they can be composed via
``Depends()`` and ``Security()`` in router-level ``dependencies=[...]``.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query, Security
from fastapi.security import APIKeyHeader

_IST = ZoneInfo("Asia/Kolkata")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_auth(key: str | None = Security(_api_key_header)) -> None:
    """Reject requests that don't carry a valid X-API-Key header.

    When ``API_AUTH_KEY`` is empty (default in dev) the check is bypassed so
    local development never requires a key.  Set ``API_AUTH_KEY`` in prod .env.
    """
    from pdp.settings import get_settings

    expected = get_settings().API_AUTH_KEY
    if not expected:
        # Auth disabled — empty string means dev/open mode.
        return
    if key != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


class PaginationParams:
    """Bounded pagination dependency: ``limit`` 1–500, ``offset`` ≥0.

    Usage::

        @router.get("/items")
        async def list_items(pagination: Annotated[PaginationParams, Depends()]):
            ...
    """

    def __init__(
        self,
        limit: int = Query(50, ge=1, le=500, description="Max items to return (1–500)"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ) -> None:
        self.limit = limit
        self.offset = offset


def parse_ist_date(
    date: str | None = Query(None, description="ISO-8601 date (YYYY-MM-DD); defaults to today IST"),
) -> _date:
    """Parse an ISO-8601 date query parameter, defaulting to today (IST).

    Raises HTTP 400 on malformed input instead of letting the error propagate
    as an unhandled 500.
    """
    if not date:
        return datetime.now(_IST).date()
    try:
        return _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="date must be ISO-8601 (YYYY-MM-DD)",
        )
