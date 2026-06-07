from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select

from pdp.cli.progress.formatter import format_number, format_timestamp, print_message, print_table
from pdp.db.session import get_session_maker
from pdp.orders.models import Position
from pdp.settings import get_settings

if TYPE_CHECKING:
    from pdp.cli.progress.config import CLIConfig

log = structlog.get_logger()


def show_positions(config: CLIConfig, format_type: str) -> None:
    asyncio.run(_show_positions_async(config, format_type))


async def _show_positions_async(config: CLIConfig, format_type: str) -> None:
    settings = get_settings()
    timestamp = format_timestamp()

    if config.live_mode and settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        await _show_dhan_positions(format_type, timestamp, settings)
    else:
        await _show_db_positions(format_type, timestamp)


async def _show_dhan_positions(format_type: str, timestamp: str, settings: Any) -> None:
    try:
        from dhanhq import DhanContext, dhanhq

        ctx = DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
        client = dhanhq(ctx)

        # Fetch positions (F&O, derivatives)
        try:
            positions_resp = await asyncio.to_thread(client.get_positions)
            log.debug("dhan_positions_response", response=positions_resp)
            positions_list = positions_resp.get("data", []) if isinstance(positions_resp, dict) else []
        except Exception as pos_error:
            log.debug("position_fetch_fallback", error=str(pos_error))
            positions_list = []

        if not positions_list:
            print_message("No open F&O positions found in Dhan account", error=False)
            return

        headers = ["Symbol", "Exchange", "Type", "Qty", "Entry Pr", "Curr Pr", "P&L", "Greeks"]
        rows = []

        for pos in positions_list:
            qty = float(pos.get("netQty", pos.get("quantity", 0)))
            if qty == 0:
                continue

            symbol = pos.get("tradingSymbol", pos.get("securityId", "N/A"))
            exchange = pos.get("exchangeSegment", pos.get("exchange", "NSE"))
            position_type = pos.get("positionType", "OVERNIGHT")

            # Get entry price (use costPrice for average or buyAvg/sellAvg depending on position type)
            if qty > 0:
                entry_price = float(pos.get("buyAvg", pos.get("costPrice", 0)))
            else:
                entry_price = float(pos.get("sellAvg", pos.get("costPrice", 0)))

            # Unrealized profit is directly provided by Dhan
            unrealized_pnl = float(pos.get("unrealizedProfit", 0))

            # Calculate current price from unrealized P&L if needed
            if qty != 0 and unrealized_pnl != 0:
                current_price = entry_price + (unrealized_pnl / abs(qty))
            else:
                current_price = entry_price

            # Check if it's an option (has Greeks or contains CE/PE)
            delta = pos.get("delta", 0)
            is_option = "CE" in symbol or "PE" in symbol or delta != 0
            greeks_str = f"D:{delta:.2f}" if is_option else "-"

            rows.append(
                [
                    symbol,
                    exchange,
                    position_type,
                    str(int(qty)),
                    format_number(entry_price),
                    format_number(current_price),
                    format_number(unrealized_pnl),
                    greeks_str,
                ]
            )

        if format_type == "json":
            json_data = {
                "timestamp": timestamp,
                "mode": "live",
                "type": "F&O Positions",
                "count": len(positions_list),
                "positions": [
                    {
                        "symbol": pos.get("tradingSymbol"),
                        "exchange": pos.get("exchangeSegment"),
                        "position_type": pos.get("positionType"),
                        "quantity": int(pos.get("netQty", 0)),
                        "entry_price": float(pos.get("buyAvg") if pos.get("netQty", 0) > 0 else pos.get("sellAvg", 0)),
                        "unrealized_pnl": float(pos.get("unrealizedProfit", 0)),
                        "expiry": pos.get("drvExpiryDate", ""),
                        "option_type": pos.get("drvOptionType", ""),
                        "strike": float(pos.get("drvStrikePrice", 0)) if pos.get("drvStrikePrice") else None,
                    }
                    for pos in positions_list
                    if pos.get("netQty", 0) != 0
                ],
            }
            print(json.dumps(json_data, indent=2, default=str))
        else:
            print_table("Dhan F&O Positions (Overnight)", headers, rows, format_type)

    except Exception as e:
        print_message(f"Failed to fetch Dhan positions: {e}", error=True)
        log.warning("dhan_positions_fetch_failed", error=str(e))


async def _show_db_positions(format_type: str, timestamp: str) -> None:
    async with get_session_maker()() as session:
        result = await session.execute(select(Position).where(Position.net_qty != 0))
        positions = result.scalars().all()

        if not positions:
            print_message("No positions found", error=False)
            return

        headers = ["Symbol", "Segment", "Product", "Qty", "Entry Price", "Current Price", "P&L", "Updated"]
        rows = []

        for pos in positions:
            rows.append(
                [
                    pos.security_id,
                    pos.exchange_segment,
                    pos.product,
                    str(pos.net_qty),
                    format_number(float(pos.avg_price)),
                    format_number(float(pos.avg_price)),
                    format_number(float(pos.unrealized_pnl or Decimal("0"))),
                    pos.updated_at.isoformat() if pos.updated_at else "N/A",
                ]
            )

        if format_type == "json":
            json_data = {
                "timestamp": timestamp,
                "mode": "paper",
                "count": len(positions),
                "positions": [
                    {
                        "security_id": pos.security_id,
                        "exchange_segment": pos.exchange_segment,
                        "product": pos.product,
                        "net_qty": pos.net_qty,
                        "avg_price": float(pos.avg_price),
                        "unrealized_pnl": float(pos.unrealized_pnl or Decimal("0")),
                        "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
                    }
                    for pos in positions
                ],
            }
            print(json.dumps(json_data, indent=2))
        else:
            print_table("Paper Positions", headers, rows, format_type)
