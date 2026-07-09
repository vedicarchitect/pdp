"""Option strike resolution for strategies.

Resolves a tradeable option ``Instrument`` (security_id, segment, lot_size) for a given
underlying, spot, side (CE/PE) and out-of-the-money offset, using the local instruments
table. The strategy passes the returned ``security_id`` to the order router.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select

from pdp.instruments.models import Instrument

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

_IST = ZoneInfo("Asia/Kolkata")

# Strike spacing per underlying (index options).
STRIKE_STEP: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100,
}


def _ist_today() -> date:
    from datetime import datetime

    return datetime.now(_IST).date()


def atm_strike(spot: float, strike_step: int) -> int:
    """Round spot to the nearest strike on the ``strike_step`` grid."""
    return int(round(spot / strike_step) * strike_step)


def otm_strike(spot: float, option_type: str, otm_steps: int, strike_step: int) -> int:
    """ATM shifted ``otm_steps`` out-of-the-money (PE below spot, CE above spot)."""
    atm = atm_strike(spot, strike_step)
    if option_type.upper() == "PE":
        return atm - otm_steps * strike_step
    return atm + otm_steps * strike_step


async def nearest_expiry(
    session: AsyncSession, underlying: str, on_or_after: date | None = None
) -> date | None:
    """Smallest option expiry for ``underlying`` on or after a date (IST today by default).

    Cadence-agnostic: it returns the real next tradeable expiry from the instruments table
    (the Dhan scrip master) regardless of weekly/monthly/weekday regime — never a projected
    weekday. Returns ``None`` when the table has no matching expiry (caller degrades honestly).
    """
    floor = on_or_after or _ist_today()
    result = await session.execute(
        select(func.min(Instrument.expiry)).where(
            Instrument.underlying == underlying,
            Instrument.option_type.in_(["CE", "PE"]),
            Instrument.expiry >= floor,
        )
    )
    return result.scalar_one_or_none()


# Back-compat alias — the query has always been cadence-agnostic; the old name wrongly
# implied "weekly". Prefer ``nearest_expiry`` in new code.
nearest_weekly_expiry = nearest_expiry


async def resolve_otm_option(
    session: AsyncSession,
    *,
    underlying: str,
    spot: float,
    option_type: str,
    otm_steps: int = 1,
    strike_step: int | None = None,
    expiry: date | None = None,
) -> Instrument | None:
    """Return the OTM option ``Instrument`` for the nearest expiry, or None.

    Returns ``None`` when the instruments table has no matching row (e.g. not loaded for
    today's expiry) — callers should skip trading rather than guess a security_id.
    """
    step = strike_step or STRIKE_STEP.get(underlying.upper(), 50)
    if expiry is None:
        expiry = await nearest_expiry(session, underlying)
    if expiry is None:
        log.warning("no_expiry_found", underlying=underlying)
        return None

    strike = otm_strike(spot, option_type, otm_steps, step)
    result = await session.execute(
        select(Instrument)
        .where(
            Instrument.underlying == underlying,
            Instrument.expiry == expiry,
            Instrument.option_type == option_type.upper(),
            Instrument.strike == Decimal(str(strike)),
        )
        .limit(1)
    )
    inst = result.scalar_one_or_none()
    if inst is None:
        log.warning(
            "no_instrument_for_strike",
            underlying=underlying,
            expiry=str(expiry),
            option_type=option_type,
            strike=strike,
        )
    return inst
