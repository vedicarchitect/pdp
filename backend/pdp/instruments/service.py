from __future__ import annotations

from datetime import date

from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.instruments.models import Instrument


async def search(
    session: AsyncSession,
    *,
    q: str | None = None,
    segment: str | None = None,
    instrument_type: str | None = None,
    underlying: str | None = None,
    expiry: date | None = None,
    limit: int = 20,
) -> list[Instrument]:
    stmt = select(Instrument)
    conds = []
    if q:
        like = f"%{q}%"
        conds.append(or_(Instrument.trading_symbol.ilike(like), Instrument.underlying.ilike(like)))
    if segment:
        conds.append(Instrument.exchange_segment == segment)
    if instrument_type:
        conds.append(Instrument.instrument_type == instrument_type)
    if underlying:
        conds.append(Instrument.underlying == underlying)
    if expiry:
        conds.append(Instrument.expiry == expiry)
    if conds:
        stmt = stmt.where(and_(*conds))

    if q:
        prefix = f"{q}%"
        rank = case(
            (Instrument.trading_symbol == q, 0),
            (Instrument.trading_symbol.ilike(prefix), 1),
            else_=2,
        )
        stmt = stmt.order_by(rank, Instrument.trading_symbol)
    else:
        stmt = stmt.order_by(Instrument.updated_at.desc())

    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_by_id(
    session: AsyncSession, security_id: str, segment: str
) -> Instrument | None:
    stmt = select(Instrument).where(
        Instrument.security_id == security_id,
        Instrument.exchange_segment == segment,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
