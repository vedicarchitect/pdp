"""EOD position reconcile module.

After the daily broker-sync completes, ``reconcile_day_positions`` compares
each PG strategy position against the matching broker position and flags any
net-qty mismatches.  Discrepancies trigger a POSITION_RECONCILE_MISMATCH
critical event so the operator sees them in the execution console alert feed
immediately.

Design constraints:
* Read-only: never mutates PG positions (that is the operator's job).
* Non-blocking: all mismatches are logged + emitted; the function returns even
  if event emission fails.
* Idempotent: can be called multiple times per day without side effects.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger()


async def reconcile_day_positions(
    session_maker: async_sessionmaker[AsyncSession],
    broker_positions: list[dict[str, Any]],
    event_service: Any | None = None,
) -> dict[str, Any]:
    """Compare PG strategy positions vs. broker positions; emit alerts on mismatch.

    Args:
        session_maker: Async SQLAlchemy session factory.
        broker_positions: Raw position dicts from the broker API (Dhan format).
        event_service: Optional EventService for POSITION_RECONCILE_MISMATCH alerts.
            Pass ``None`` in paper / cred-less mode.

    Returns:
        dict with keys:
            ``checked``   — number of unique security_ids checked
            ``mismatches``— list of {security_id, internal, broker} dicts
            ``alerted``   — number of mismatches that triggered a critical event
    """
    from sqlalchemy import select

    from pdp.events.models import EventType
    from pdp.orders.models import Position

    # ── Step 1: aggregate internal net qty by security_id ────────────────────
    internal: dict[str, int] = {}
    async with session_maker() as session:
        positions = (await session.scalars(select(Position))).all()
        for pos in positions:
            sid = pos.security_id
            internal[sid] = internal.get(sid, 0) + int(pos.net_qty)

    # ── Step 2: aggregate broker net qty by security_id ──────────────────────
    def _get(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in row and row[k] is not None:
                return row[k]
        return default

    def _int_safe(v: Any) -> int:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0

    broker: dict[str, int] = {}
    for p in broker_positions:
        sid = str(_get(p, "securityId", "security_id", default=""))
        if sid:
            broker[sid] = broker.get(sid, 0) + _int_safe(_get(p, "netQty", "net_qty", default=0))

    # ── Step 3: detect mismatches and emit POSITION_RECONCILE_MISMATCH ───────
    mismatches: list[dict[str, Any]] = []
    alerted = 0

    for sid in set(internal) | set(broker):
        iqty = internal.get(sid, 0)
        bqty = broker.get(sid, 0)
        if iqty == bqty:
            continue

        mismatch = {
            "security_id": sid,
            "internal": iqty,
            "broker": bqty,
            "delta": bqty - iqty,
        }
        mismatches.append(mismatch)
        log.warning(
            "eod_position_mismatch",
            security_id=sid,
            internal=iqty,
            broker=bqty,
            delta=bqty - iqty,
        )

        if event_service is not None:
            try:
                event_service.emit_critical(
                    EventType.POSITION_RECONCILE_MISMATCH,
                    sid,
                    "EOD position mismatch",
                    f"security {sid}: internal={iqty} vs broker={bqty} (Δ={bqty - iqty})",
                    mismatch,
                )
                alerted += 1
            except Exception as exc:
                log.warning("eod_reconcile_alert_failed", sid=sid, exc=str(exc))

    checked = len(set(internal) | set(broker))
    log.info(
        "eod_reconcile_done",
        checked=checked,
        mismatches=len(mismatches),
        alerted=alerted,
    )
    return {"checked": checked, "mismatches": mismatches, "alerted": alerted}
