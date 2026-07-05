from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

import structlog

log = structlog.get_logger()


@dataclass
class FIIDIIData:
    date: date
    fii_index_futures_net: float
    fii_index_options_net: float
    fii_stock_futures_net: float
    dii_index_futures_net: float
    dii_index_options_net: float
    dii_stock_futures_net: float

class FIIDIISource(Protocol):
    async def fetch(self, d: date) -> FIIDIIData | None: ...

class StubFIIDIISource:
    async def fetch(self, d: date) -> FIIDIIData | None:
        return None  # No data available


class NseFIIDIISource:
    """Provisional daily FII/DII net flow via nsepython.

    `nsepython.nse_fiidii()` returns NSE's own provisional same-day figure (cash-market
    buy/sell/net for FII/FPI and DII) — it does not break flows down by index-futures /
    index-options / stock-futures the way `FIIDIIData` models. We surface the cash-market net
    figures via the futures/options-agnostic fields NSE actually publishes and leave the
    per-instrument breakdown fields at 0.0 (not fabricated — NSE's free provisional feed
    simply doesn't carry that granularity). `fetch()` runs `nsepython` in a thread-pool
    executor — it performs blocking HTTP, never call it inline on a request path.
    """

    async def fetch(self, d: date) -> FIIDIIData | None:
        rows = await asyncio.to_thread(self._fetch_sync)
        if not rows:
            return None
        target = self._match_row(rows, d)
        return target

    async def fetch_range(self, days: int) -> list[FIIDIIData]:
        """Return up to `days` most recent trading days of FII/DII net flow."""
        rows = await asyncio.to_thread(self._fetch_sync)
        return rows[:days]

    def _fetch_sync(self) -> list[FIIDIIData]:
        try:
            import nsepython

            raw = nsepython.nse_fiidii()
        except Exception as exc:
            log.warning("nse_fiidii_fetch_failed", exc=str(exc))
            return []

        by_date: dict[date, dict[str, float]] = {}
        try:
            records = raw.to_dict("records") if hasattr(raw, "to_dict") else raw
            for row in records:
                d = self._parse_date(row.get("date"))
                if d is None:
                    continue
                category = str(row.get("category", "")).upper()
                net = float(row.get("netValue", 0.0) or 0.0)
                bucket = by_date.setdefault(d, {"FII": 0.0, "DII": 0.0})
                if "FII" in category or "FPI" in category:
                    bucket["FII"] += net
                elif "DII" in category:
                    bucket["DII"] += net
        except Exception as exc:
            log.warning("nse_fiidii_parse_failed", exc=str(exc))
            return []

        results = [
            FIIDIIData(
                date=d,
                fii_index_futures_net=0.0,
                fii_index_options_net=0.0,
                fii_stock_futures_net=vals["FII"],
                dii_index_futures_net=0.0,
                dii_index_options_net=0.0,
                dii_stock_futures_net=vals["DII"],
            )
            for d, vals in by_date.items()
        ]
        results.sort(key=lambda r: r.date, reverse=True)
        return results

    @staticmethod
    def _parse_date(raw: object) -> date | None:
        if not raw:
            return None
        for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
            try:
                from datetime import datetime

                return datetime.strptime(str(raw), fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _match_row(rows: list[FIIDIIData], d: date) -> FIIDIIData | None:
        for row in rows:
            if row.date == d:
                return row
        # NSE's provisional feed only ever carries the last few sessions; fall back to the
        # most recent row when asked for "today" and today isn't published yet.
        if rows and d >= max(r.date for r in rows) - timedelta(days=1):
            return rows[0]
        return None
