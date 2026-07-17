"""On-demand indicator suite for the current NIFTY ATM call/put option.

Unlike the spot/futures indicator matrix (fed continuously by the live ``IndicatorEngine``
via ``BarAggregator``), option-strike ``option_bars`` are written by the warehouse's own 1m
aggregator (``pdp.warehouse.service``) and never reach the live engine — the ATM strike
also changes as spot moves, so a persistent per-strike tracker would churn constantly for
no benefit. Instead this module resolves the current ATM CE/PE security ids, reads their
stored 1m ``option_bars``, rolls them up to the matrix timeframes with the same
session-anchored bucket function the live feed uses, and runs a throwaway
``IndicatorEngine`` over just that history — computed fresh on each request, not cached.

Camarilla/period-levels are index-only concepts (`levels-warehouse` computes them from the
spot index) and are intentionally omitted here.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import structlog

from pdp.indicators.engine import IndicatorEngine
from pdp.market.bars import BarClosed, rollup_1m_bars
from pdp.strategy.strikes import STRIKE_STEP, atm_strike, nearest_expiry, resolve_otm_option

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Suite families the ATM CE/PE rows need — same families the index matrix cells expose,
# minus pivots/period_levels (index-only). VWAP/VWMA are meaningful here since options
# carry their own traded volume, unlike the spot index.
_ATM_SUITE_INDICATORS: list[dict[str, Any]] = [
    {"family": "ema", "periods": [9, 20, 50, 100, 200]},
    {"family": "rsi", "period": 14, "ma_period": 14},
    {"family": "vwap"},
    {"family": "vwma", "period": 20},
]

_ROLLUP_TF_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "30m": 30, "1H": 60}


async def resolve_nifty_atm_option(
    session: AsyncSession, spot: float, option_type: str
) -> tuple[str, float, date] | None:
    """Resolve the current NIFTY ATM CE or PE: (security_id, strike, expiry), or None if
    the instruments table has no matching row for today's expiry (degrade honestly rather
    than guessing a security_id)."""
    step = STRIKE_STEP["NIFTY"]
    expiry = await nearest_expiry(session, "NIFTY")
    if expiry is None:
        return None
    inst = await resolve_otm_option(
        session, underlying="NIFTY", spot=spot, option_type=option_type,
        otm_steps=0, strike_step=step, expiry=expiry,
    )
    if inst is None:
        return None
    return inst.security_id, atm_strike(spot, step), expiry


async def _fetch_option_1m_bars(
    option_bars_col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    security_id: str,
    since: datetime,
) -> list[BarClosed]:
    """Load an option contract's stored 1m bars as BarClosed, oldest first."""
    cursor = option_bars_col.find(
        {"security_id": security_id, "timeframe": "1m", "ts": {"$gte": since}},
        sort=[("ts", 1)],
    )
    bars: list[BarClosed] = []
    async for doc in cursor:
        ts = doc["ts"] if doc["ts"].tzinfo else doc["ts"].replace(tzinfo=UTC)
        bars.append(
            BarClosed(
                security_id=security_id,
                timeframe="1m",
                bar_time=ts,
                open=doc["open"],
                high=doc["high"],
                low=doc["low"],
                close=doc["close"],
                volume=doc.get("volume") or 0,
                oi=doc.get("oi") or 0,
            )
        )
    return bars


async def build_atm_option_row(
    option_bars_col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    security_id: str,
    strike: float,
    expiry: date,
    opt_type: str,
    matrix_tfs: list[str],
    since: datetime,
) -> dict[str, Any]:
    """Build one ATM CE/PE matrix row: {label, strike, expiry, tf: {...cells}}.

    Each timeframe cell is populated only from that timeframe's own rolled-up bars; a
    timeframe with fewer bars than an indicator's required depth simply omits that
    indicator's field (never a partial/fabricated value) — the engine's own trackers
    already degrade this way (see indicator-history-depth).
    """
    bars_1m = await _fetch_option_1m_bars(option_bars_col, security_id, since)

    row: dict[str, Any] = {
        "label": f"NIFTY {int(strike)} {opt_type}",
        "strike": strike,
        "expiry": expiry.isoformat(),
        "security_id": security_id,
        "tf": {},
    }
    if not bars_1m:
        row["tf"] = {tf: {} for tf in matrix_tfs}
        return row

    for tf in matrix_tfs:
        tf_minutes = _ROLLUP_TF_MINUTES.get(tf)
        if tf_minutes is None:
            row["tf"][tf] = {}  # 1D not derived from 1m here; omit rather than guess
            continue

        tf_bars = rollup_1m_bars(bars_1m, tf_minutes, tf)
        if not tf_bars:
            row["tf"][tf] = {}
            continue

        engine = IndicatorEngine(timeframes=[tf])
        engine.configure_suite(security_id, tf, _ATM_SUITE_INDICATORS)
        engine.seed_from_bars(tf_bars)

        cell: dict[str, Any] = {}
        ema_state = engine.get_ema(security_id, tf)
        if ema_state:
            cell["ema9"] = ema_state.values.get(9)
            cell["ema20"] = ema_state.values.get(20)
            cell["ema50"] = ema_state.values.get(50)
            cell["ema100"] = ema_state.values.get(100)
            cell["ema200"] = ema_state.values.get(200)
        rsi_state = engine.get_rsi(security_id, tf)
        if rsi_state:
            cell["rsi"] = rsi_state.rsi
            cell["rsi_ma"] = rsi_state.ma
        vwap_state = engine.get_vwap(security_id, tf)
        if vwap_state:
            cell["vwap"] = vwap_state.vwap
        vwma_state = engine.get_vwma(security_id, tf)
        if vwma_state:
            cell["vwma"] = vwma_state.vwma
        for label, variant_state in engine.get_supertrend_variants(security_id, tf).items():
            cell[label] = {
                "value": float(variant_state.value) if variant_state.value else None,
                "direction": "up" if variant_state.direction == 1 else "down",
            }
        st_state = engine.get(security_id, tf)
        if st_state:
            cell["st_val"] = float(st_state.value) if st_state.value else None
            cell["st_dir"] = "up" if st_state.direction == 1 else "down"

        row["tf"][tf] = cell

    return row
