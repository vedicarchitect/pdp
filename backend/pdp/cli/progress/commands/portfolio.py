from __future__ import annotations

import asyncio
import json
from collections import defaultdict
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
        except Exception as e:
            log.warning("dhan_holdings_fetch_failed", error=str(e))
            print_message(f"Warning: could not fetch equity holdings: {e}", error=True)

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
        except Exception as e:
            log.warning("dhan_fno_positions_fetch_failed", error=str(e))
            print_message(f"Warning: could not fetch F&O positions: {e}", error=True)

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

        # Group by exchange_segment for the by-segment breakdown.
        seg_unrealized: dict[str, Decimal] = defaultdict(Decimal)
        seg_realized: dict[str, Decimal] = defaultdict(Decimal)
        seg_open: dict[str, int] = defaultdict(int)

        for pos in positions:
            u = pos.unrealized_pnl or Decimal("0")
            r = pos.realized_pnl or Decimal("0")
            total_unrealized += u
            total_realized += r
            seg = pos.exchange_segment or "UNKNOWN"
            seg_unrealized[seg] += u
            seg_realized[seg] += r
            if pos.net_qty != 0:
                seg_open[seg] += 1

        open_count = sum(seg_open.values())

        if format_type == "json":
            json_data = {
                "timestamp": timestamp,
                "mode": mode,
                "summary": {
                    "total_unrealized_pnl": float(total_unrealized),
                    "total_realized_pnl": float(total_realized),
                    "total_pnl": float(total_unrealized + total_realized),
                    "open_positions": open_count,
                },
                "by_segment": {
                    seg: {
                        "open_positions": seg_open.get(seg, 0),
                        "unrealized_pnl": float(seg_unrealized[seg]),
                        "realized_pnl": float(seg_realized[seg]),
                    }
                    for seg in sorted(seg_unrealized)
                },
            }
            print(json.dumps(json_data, indent=2))
        else:
            summary_rows = [
                ["Mode", mode],
                ["Total Unrealized P&L", format_number(float(total_unrealized))],
                ["Total Realized P&L", format_number(float(total_realized))],
                ["Total P&L", format_number(float(total_unrealized + total_realized))],
                ["Open Positions", str(open_count)],
                ["Timestamp", timestamp],
            ]
            print_table("Portfolio Summary", ["Metric", "Value"], summary_rows, format_type)

            if seg_unrealized:
                seg_rows = [
                    [
                        seg,
                        str(seg_open.get(seg, 0)),
                        format_number(float(seg_unrealized[seg])),
                        format_number(float(seg_realized[seg])),
                    ]
                    for seg in sorted(seg_unrealized)
                ]
                print_table(
                    "By Segment",
                    ["Segment", "Open Pos", "Unrealized P&L", "Realized P&L"],
                    seg_rows,
                    format_type,
                )
