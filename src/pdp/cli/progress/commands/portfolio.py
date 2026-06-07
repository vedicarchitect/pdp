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


def show_portfolio(config: CLIConfig, format_type: str) -> None:
    asyncio.run(_show_portfolio_async(config, format_type))


async def _show_portfolio_async(config: CLIConfig, format_type: str) -> None:
    settings = get_settings()
    mode = "live" if settings.LIVE else "paper"
    timestamp = format_timestamp()

    if config.live_mode and settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        await _show_dhan_portfolio(format_type, timestamp, settings, mode)
    else:
        await _show_db_portfolio(format_type, timestamp, mode)


async def _show_dhan_portfolio(format_type: str, timestamp: str, settings: Any, mode: str) -> None:
    try:
        from dhanhq import DhanContext, dhanhq

        ctx = DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
        client = dhanhq(ctx)

        # Fetch equity holdings
        total_invested = 0.0
        total_current = 0.0
        total_pnl = 0.0
        equity_count = 0

        try:
            holdings = await asyncio.to_thread(client.get_holdings)
            if holdings and isinstance(holdings, dict):
                holdings_list = holdings.get("data", [])
                if isinstance(holdings_list, list):
                    for pos in holdings_list:
                        qty = float(pos.get("totalQty", 0))
                        if qty == 0:
                            continue
                        equity_count += 1
                        entry_price = float(pos.get("avgCostPrice", 0))
                        current_price = float(pos.get("lastTradedPrice", entry_price))
                        invested = entry_price * qty
                        current = current_price * qty
                        pnl = current - invested
                        total_invested += invested
                        total_current += current
                        total_pnl += pnl
        except Exception:
            pass

        # Fetch F&O positions
        fno_count = 0
        try:
            positions_resp = await asyncio.to_thread(client.get_positions)
            if positions_resp and isinstance(positions_resp, dict):
                positions_list = positions_resp.get("data", [])
                if isinstance(positions_list, list):
                    for pos in positions_list:
                        if pos.get("netQty", 0) == 0:
                            continue
                        fno_count += 1
                        # F&O P&L is directly provided
                        total_pnl += float(pos.get("unrealizedProfit", 0))
        except Exception:
            pass

        positions_list = []  # Not used after this point in this function

        if format_type == "json":
            json_data = {
                "timestamp": timestamp,
                "mode": mode,
                "summary": {
                    "total_invested": total_invested,
                    "total_current_value": total_current,
                    "total_unrealized_pnl": total_pnl,
                    "total_realized_pnl": 0.0,
                    "total_pnl": total_pnl,
                    "equity_holdings": equity_count,
                    "fno_positions": fno_count,
                },
            }
            print(json.dumps(json_data, indent=2))
        else:
            headers = ["Metric", "Value"]
            rows = [
                ["Mode", mode],
                ["Total Invested (Equity)", format_number(total_invested)],
                ["Current Value (Equity)", format_number(total_current)],
                ["Total P&L (Equity + F&O)", format_number(total_pnl)],
                ["Realized P&L", format_number(0.0)],
                ["Equity Holdings", str(equity_count)],
                ["F&O Positions", str(fno_count)],
                ["Timestamp", timestamp],
            ]

            print_table("Portfolio Summary (Live Dhan)", headers, rows, format_type)

    except Exception as e:
        print_message(f"Failed to fetch Dhan portfolio: {e}", error=True)
        log.warning("dhan_portfolio_fetch_failed", error=str(e))


async def _show_db_portfolio(format_type: str, timestamp: str, mode: str) -> None:
    async with get_session_maker()() as session:
        result = await session.execute(select(Position))
        positions = result.scalars().all()

        total_unrealized = Decimal("0")
        total_realized = Decimal("0")

        for pos in positions:
            total_unrealized += pos.unrealized_pnl or Decimal("0")
            total_realized += pos.realized_pnl or Decimal("0")

        if format_type == "json":
            json_data = {
                "timestamp": timestamp,
                "mode": mode,
                "summary": {
                    "total_unrealized_pnl": float(total_unrealized),
                    "total_realized_pnl": float(total_realized),
                    "total_pnl": float(total_unrealized + total_realized),
                    "open_positions": len([p for p in positions if p.net_qty != 0]),
                },
            }
            print(json.dumps(json_data, indent=2))
        else:
            headers = ["Metric", "Value"]
            rows = [
                ["Mode", mode],
                ["Total Unrealized P&L", format_number(float(total_unrealized))],
                ["Total Realized P&L", format_number(float(total_realized))],
                ["Total P&L", format_number(float(total_unrealized + total_realized))],
                ["Open Positions", str(len([p for p in positions if p.net_qty != 0]))],
                ["Timestamp", timestamp],
            ]

            print_table("Portfolio Summary", headers, rows, format_type)
