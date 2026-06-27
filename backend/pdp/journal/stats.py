"""Pure daily-stats computation over journal fills.

Each trade entry is a dict: ``security_id, side ("BUY"/"SELL"), qty, fill_price, charges``.
For an intraday strategy that is flat by EOD, realized P&L = total sell proceeds - total buy
cost - total charges. Per-security round-trips (sold and fully bought back) drive win/loss.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def _d(v: Any) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def compute_daily_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    sell_value = Decimal("0")
    buy_value = Decimal("0")
    total_charges = Decimal("0")
    sells = 0
    buys = 0

    # Per-security accumulators for round-trip detection / win-loss.
    per_sec: dict[str, dict[str, Decimal]] = {}

    for t in trades:
        sid = str(t.get("security_id", ""))
        side = str(t.get("side", "")).upper()
        qty = _d(t.get("qty", 0))
        price = _d(t.get("fill_price", 0))
        charges = _d(t.get("charges", 0))
        value = qty * price
        total_charges += charges

        acc = per_sec.setdefault(
            sid,
            {
                "sell_qty": Decimal("0"),
                "buy_qty": Decimal("0"),
                "sell_val": Decimal("0"),
                "buy_val": Decimal("0"),
                "charges": Decimal("0"),
            },
        )
        acc["charges"] += charges
        if side == "SELL":
            sell_value += value
            sells += 1
            acc["sell_qty"] += qty
            acc["sell_val"] += value
        elif side == "BUY":
            buy_value += value
            buys += 1
            acc["buy_qty"] += qty
            acc["buy_val"] += value

    net_premium = sell_value - buy_value
    realized_pnl = net_premium - total_charges

    round_trips = 0
    wins = 0
    losses = 0
    for acc in per_sec.values():
        closed = acc["sell_qty"] > 0 and acc["buy_qty"] >= acc["sell_qty"]
        if not closed:
            continue
        round_trips += 1
        pnl = acc["sell_val"] - acc["buy_val"] - acc["charges"]
        if pnl > 0:
            wins += 1
        else:
            losses += 1

    win_rate = float(wins / round_trips) if round_trips else 0.0

    return {
        "total_trades": len(trades),
        "sells": sells,
        "buys": buys,
        "securities_traded": len(per_sec),
        "gross_premium_sold": float(sell_value),
        "gross_premium_bought": float(buy_value),
        "net_premium": float(net_premium),
        "total_charges": float(total_charges),
        "realized_pnl": float(realized_pnl),
        "round_trips": round_trips,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
    }
