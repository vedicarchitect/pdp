from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import polars as pl
import structlog
from sqlalchemy import select

from pdp.cli.progress.formatter import format_number, format_timestamp, print_message, print_table
from pdp.db.session import get_session_maker
from pdp.instruments.service import get_by_id
from pdp.options import greeks as greeks_engine
from pdp.options.dhan_client import fetch_chain
from pdp.options.poller import parse_chain, spot_of
from pdp.orders.models import Position
from pdp.settings import get_settings

if TYPE_CHECKING:
    from pdp.cli.progress.config import CLIConfig

log = structlog.get_logger()


def show_greeks(config: CLIConfig, format_type: str) -> None:
    asyncio.run(_show_greeks_async(config, format_type))


async def _show_greeks_async(config: CLIConfig, format_type: str) -> None:
    settings = get_settings()
    if not settings.DHAN_ACCESS_TOKEN or not settings.DHAN_CLIENT_ID:
        print_message("Dhan credentials not configured. Cannot compute Greeks.", error=True)
        return

    token = settings.DHAN_ACCESS_TOKEN
    client_id = settings.DHAN_CLIENT_ID
    rate = settings.OPTIONS_RISK_FREE_RATE

    # 1. Load open option positions and resolve their instrument metadata.
    async with get_session_maker()() as session:
        result = await session.execute(select(Position).where(Position.net_qty != 0))
        positions = list(result.scalars().all())

        legs: list[dict] = []
        for pos in positions:
            inst = await get_by_id(session, pos.security_id, pos.exchange_segment)
            if inst is None or inst.option_type not in ("CE", "PE"):
                continue
            if inst.underlying is None or inst.expiry is None or inst.strike is None:
                continue
            legs.append(
                {
                    "symbol": inst.trading_symbol,
                    "underlying": inst.underlying.upper(),
                    "expiry": inst.expiry.isoformat(),
                    "strike": float(inst.strike),
                    "side": "ce" if inst.option_type == "CE" else "pe",
                    "qty": pos.net_qty,
                    "avg_price": float(pos.avg_price),
                }
            )

    if not legs:
        print_message("No open option positions found", error=False)
        return

    # 2. Fetch + parse one chain per (underlying, expiry); reuse the corrected pipeline.
    groups: dict[tuple[str, str], dict] = {}
    first = True
    for leg in legs:
        key = (leg["underlying"], leg["expiry"])
        if key in groups:
            continue
        if not first:
            await asyncio.sleep(3)  # Dhan option-chain rate limit
        first = False
        try:
            raw = await fetch_chain(leg["underlying"], leg["expiry"], token, client_id)
        except Exception as e:
            log.warning("greeks_chain_fetch_failed", **dict(zip(("underlying", "expiry"), key)), error=str(e))
            groups[key] = {"spot": 0.0, "by_strike": {}}
            continue
        spot = spot_of(raw)
        by_strike = {s["strike"]: s for s in parse_chain(raw, leg["underlying"], rate)}
        groups[key] = {"spot": spot, "by_strike": by_strike}

    # 3. Resolve greeks per leg (chain row if present, else vollib fallback).
    # Position-level greeks are sign-adjusted: short positions (qty < 0) negate
    # the theoretical option greeks so the table reflects actual exposure.
    timestamp = format_timestamp()
    greeks_data: list[dict] = []
    for leg in legs:
        grp = groups[(leg["underlying"], leg["expiry"])]
        row = grp["by_strike"].get(leg["strike"])
        if row is not None:
            g = row[leg["side"]]
        else:
            g = _fallback_greeks(leg, grp["spot"], rate)
        sign = -1 if leg["qty"] < 0 else 1
        greeks_data.append(
            {
                "symbol": leg["symbol"],
                "type": leg["side"].upper(),
                "strike": leg["strike"],
                "qty": leg["qty"],
                "avg_price": leg["avg_price"],
                "iv": g["iv"],
                "delta": sign * g["delta"],
                "gamma": sign * g["gamma"],
                "theta": sign * g["theta"],
                "vega": sign * g["vega"],
            }
        )

    if format_type == "json":
        print(json.dumps({"timestamp": timestamp, "count": len(greeks_data), "positions": greeks_data}, indent=2, default=str))
        return

    headers = ["Symbol", "Type", "Strike", "Qty", "Avg Price", "IV", "Delta", "Gamma", "Theta", "Vega"]
    rows = [
        [
            g["symbol"],
            g["type"],
            format_number(g["strike"], 0),
            str(g["qty"]),
            format_number(g["avg_price"]),
            format_number(g["iv"], 4),
            format_number(g["delta"], 4),
            format_number(g["gamma"], 4),
            format_number(g["theta"], 4),
            format_number(g["vega"], 4),
        ]
        for g in greeks_data
    ]
    print_table("Greeks for Open Positions", headers, rows, format_type)


def _fallback_greeks(leg: dict, spot: float, rate: float) -> dict:
    """Compute greeks via vollib when the strike is absent from the chain."""
    from datetime import date

    df = pl.DataFrame(
        {
            "strike": [leg["strike"]],
            "ce_ltp": [leg["avg_price"] if leg["side"] == "ce" else 0.0],
            "pe_ltp": [leg["avg_price"] if leg["side"] == "pe" else 0.0],
        }
    )
    out = greeks_engine.compute_greeks(df, spot, date.fromisoformat(leg["expiry"]), rate).row(0, named=True)
    p = leg["side"]
    return {
        "iv": float(out[f"{p}_iv"]),
        "delta": float(out[f"{p}_delta"]),
        "gamma": float(out[f"{p}_gamma"]),
        "theta": float(out[f"{p}_theta"]),
        "vega": float(out[f"{p}_vega"]),
    }
