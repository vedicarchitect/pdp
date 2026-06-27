"""Portfolio stats digest detector (# trades, premium received, P&L, max profit/loss)."""
from __future__ import annotations

from typing import Any

from pdp.events.models import Event, EventType, Severity


class PortfolioDetectors:
    """Builds the periodic PORTFOLIO_STATS digest and tracks running P&L extremes."""

    def __init__(self) -> None:
        self._max_pnl: float = 0.0
        self._min_pnl: float = 0.0

    def build_stats(self, stats: dict[str, Any]) -> Event:
        pnl = float(stats.get("day_pnl") or stats.get("pnl") or 0.0)
        self._max_pnl = max(self._max_pnl, pnl)
        self._min_pnl = min(self._min_pnl, pnl)
        n = int(stats.get("num_trades") or 0)
        premium = float(stats.get("premium_received") or 0.0)
        realized = float(stats.get("total_realized_pnl") or stats.get("realized") or 0.0)
        unrealized = float(stats.get("total_unrealized_pnl") or stats.get("unrealized") or 0.0)
        sev = Severity.WARNING if pnl <= self._min_pnl and pnl < 0 else Severity.INFO
        return Event(
            event_type=EventType.PORTFOLIO_STATS,
            severity=sev,
            security_id="PORTFOLIO",
            title=f"P&L {pnl:+.0f} · {n} trades",
            message=(
                f"Trades {n} · premium {premium:+.0f} · P&L {pnl:+.0f} "
                f"(R {realized:+.0f} / U {unrealized:+.0f}) · "
                f"max +{self._max_pnl:.0f} / {self._min_pnl:.0f}"
            ),
            payload={
                "num_trades": n,
                "premium_received": round(premium, 2),
                "day_pnl": round(pnl, 2),
                "realized": round(realized, 2),
                "unrealized": round(unrealized, 2),
                "max_profit": round(self._max_pnl, 2),
                "max_loss": round(self._min_pnl, 2),
                "open_positions": stats.get("open_positions"),
            },
            dedup_key="PORTFOLIO:stats",
        )
