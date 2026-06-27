"""Resolve a NIFTY option contract's Dhan trading symbol (and ``security_id`` when known).

The unified ``option_bars`` warehouse stores each bar's ``trading_symbol`` so a fixed contract can
later be fetched by symbol / ``security_id`` (for positional backtests) instead of the ATM-relative
rolling-option API.

Two resolution paths:

* **Snapshot-preferred** — when a daily masters snapshot (``data/masters/<date>.csv``) covers the
  contract, return its *real* ``SEM_TRADING_SYMBOL`` and historical ``security_id``.
* **Constructed fallback** — otherwise build the canonical Dhan trading symbol deterministically.

The constructed form matches Dhan's ``SEM_TRADING_SYMBOL`` exactly, e.g. ``NIFTY-Jun2026-19150-CE``
(``{UNDERLYING}-{Mmm}{YYYY}-{STRIKE}-{CE|PE}``). Note Dhan's trading symbol does not encode the day,
so weekly contracts in the same month share a symbol — the warehouse disambiguates them by the real
``expiry_date`` in the contract key, and `security_id` (from a snapshot) is the unambiguous handle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import structlog

from pdp.instruments.snapshots import (
    DEFAULT_MASTERS_DIR,
    load_master_for_date,
    resolve_instrument,
)

log = structlog.get_logger()

# Fixed English month abbreviations (locale-independent, matches Dhan's "Mmm").
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def symbol_for(underlying: str, expiry_date: date, strike: float, option_type: str) -> str:
    """Canonical Dhan trading symbol, e.g. ``NIFTY-Jun2026-19150-CE``."""
    mon = _MONTHS[expiry_date.month - 1]
    return f"{underlying.upper()}-{mon}{expiry_date.year}-{int(round(strike))}-{option_type.upper()}"


@dataclass(slots=True)
class SymbolInfo:
    trading_symbol: str
    security_id: str | None
    source: str  # "snapshot" | "constructed"


def resolve_symbol(
    underlying: str,
    expiry_date: date,
    strike: float,
    option_type: str,
    *,
    trade_date: date | None = None,
    masters_dir: str | Path = DEFAULT_MASTERS_DIR,
) -> SymbolInfo:
    """Real symbol + ``security_id`` from a masters snapshot if available, else constructed.

    ``trade_date`` selects which day's snapshot to consult (defaults to ``expiry_date``); the
    snapshot taken on or before it is used, since a contract is only listed while active.
    """
    lookup_date = trade_date or expiry_date
    try:
        rows = load_master_for_date(lookup_date, Path(masters_dir))
    except FileNotFoundError:
        rows = None

    if rows:
        row = resolve_instrument(
            rows,
            underlying=underlying,
            option_type=option_type,
            strike=float(strike),
            expiry=expiry_date,
        )
        if row and row.get("trading_symbol"):
            sid = str(row.get("security_id") or "").strip() or None
            return SymbolInfo(str(row["trading_symbol"]).strip(), sid, "snapshot")

    return SymbolInfo(symbol_for(underlying, expiry_date, strike, option_type), None, "constructed")
