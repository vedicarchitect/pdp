"""Tests for option scrip-name resolution (constructed + snapshot-preferred)."""
from __future__ import annotations

from datetime import date

from pdp.instruments.snapshots import write_snapshot
from pdp.instruments.symbols import resolve_symbol, symbol_for


def test_symbol_for_matches_dhan_trading_symbol_format() -> None:
    # Monthly and weekly both use {UL}-{Mmm}{YYYY}-{STRIKE}-{CE|PE} (Dhan SEM_TRADING_SYMBOL).
    assert symbol_for("NIFTY", date(2026, 7, 28), 29300, "CE") == "NIFTY-Jul2026-29300-CE"
    assert symbol_for("NIFTY", date(2026, 6, 2), 19150.0, "PE") == "NIFTY-Jun2026-19150-PE"


def test_symbol_for_rounds_strike_to_int() -> None:
    assert symbol_for("NIFTY", date(2026, 6, 2), 19150.0, "ce") == "NIFTY-Jun2026-19150-CE"


def test_resolve_symbol_constructed_when_no_snapshot(tmp_path) -> None:
    info = resolve_symbol("NIFTY", date(2026, 6, 2), 19150, "CE", masters_dir=tmp_path)
    assert info.trading_symbol == "NIFTY-Jun2026-19150-CE"
    assert info.security_id is None
    assert info.source == "constructed"


def test_resolve_symbol_prefers_snapshot(tmp_path) -> None:
    # A masters snapshot covering the contract supplies the real symbol + historical security_id.
    rows = [
        {
            "security_id": "42289",
            "exchange_segment": "NSE_FNO",
            "trading_symbol": "NIFTY-Jun2026-19150-CE",
            "instrument_type": "OPTIDX",
            "underlying": "NIFTY",
            "expiry": date(2026, 6, 2),
            "strike": "19150",
            "option_type": "CE",
            "lot_size": "75",
            "tick_size": "0.05",
            "isin": "",
        }
    ]
    write_snapshot(rows, date(2026, 6, 2), masters_dir=tmp_path)

    info = resolve_symbol("NIFTY", date(2026, 6, 2), 19150, "CE", masters_dir=tmp_path)
    assert info.source == "snapshot"
    assert info.security_id == "42289"
    assert info.trading_symbol == "NIFTY-Jun2026-19150-CE"
