from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import structlog

from pdp.cli.progress.formatter import format_number, format_timestamp, print_message, print_table
from pdp.options.dhan_client import fetch_chain, fetch_expiries
from pdp.options.poller import _parse_chain
from pdp.settings import get_settings

if TYPE_CHECKING:
    from pdp.cli.progress.config import CLIConfig

log = structlog.get_logger()

_MAX_EXPIRIES = 3


def show_option_chain(
    config: CLIConfig,
    symbol: str,
    format_type: str,
    *,
    expiry: str | None = None,
    all_expiries: bool = False,
) -> None:
    asyncio.run(
        _show_option_chain_async(config, symbol, format_type, expiry, all_expiries)
    )


async def _show_option_chain_async(
    config: CLIConfig,
    symbol: str,
    format_type: str,
    expiry: str | None,
    all_expiries: bool,
) -> None:
    settings = get_settings()

    if not settings.DHAN_ACCESS_TOKEN or not settings.DHAN_CLIENT_ID:
        print_message("Dhan credentials not configured. Cannot fetch option chain.", error=True)
        return

    token = settings.DHAN_ACCESS_TOKEN
    client_id = settings.DHAN_CLIENT_ID
    rate = settings.OPTIONS_RISK_FREE_RATE

    # Resolve which expiries to fetch.
    if expiry:
        targets = [expiry]
    else:
        try:
            available = await fetch_expiries(symbol, token, client_id)
        except Exception as e:
            print_message(f"Failed to fetch expiries: {e}", error=True)
            log.warning("expiry_fetch_failed", symbol=symbol, error=str(e))
            return
        if not available:
            print_message(f"No expiries available for {symbol}", error=False)
            return
        targets = available[:_MAX_EXPIRIES] if all_expiries else available[:1]

    chains: list[tuple[str, list[dict]]] = []
    for idx, exp in enumerate(targets):
        if idx > 0:
            await asyncio.sleep(3)  # Dhan option-chain rate limit
        try:
            raw = await fetch_chain(symbol, exp, token, client_id)
        except Exception as e:
            print_message(f"Failed to fetch option chain for {exp}: {e}", error=True)
            log.warning("option_chain_fetch_failed", symbol=symbol, expiry=exp, error=str(e))
            continue
        chains.append((exp, _parse_chain(raw, symbol, rate)))

    timestamp = format_timestamp()

    if format_type == "json":
        print(
            json.dumps(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "expiries": [
                        {"expiry": exp, "strikes": strikes} for exp, strikes in chains
                    ],
                },
                indent=2,
                default=str,
            )
        )
        return

    headers = [
        "Strike",
        "CE LTP", "CE OI", "CE IV", "CE Delta",
        "PE LTP", "PE OI", "PE IV", "PE Delta",
    ]
    any_data = False
    for exp, strikes in chains:
        if not strikes:
            print_message(f"No option chain data for {symbol} {exp}", error=False)
            continue
        any_data = True
        rows = [
            [
                format_number(s["strike"], 0),
                format_number(s["ce"]["ltp"]),
                str(s["ce"]["oi"]),
                format_number(s["ce"]["iv"], 4),
                format_number(s["ce"]["delta"], 4),
                format_number(s["pe"]["ltp"]),
                str(s["pe"]["oi"]),
                format_number(s["pe"]["iv"], 4),
                format_number(s["pe"]["delta"], 4),
            ]
            for s in strikes
        ]
        print_table(f"{symbol} Option Chain — {exp} — {timestamp}", headers, rows, format_type)

    if not any_data:
        print_message(f"No option chain data available for {symbol}", error=False)
