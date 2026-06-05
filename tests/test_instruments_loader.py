from __future__ import annotations

from decimal import Decimal

from pdp.instruments.loader import parse_dhan_csv

SAMPLE_CSV = """SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SM_SYMBOL_NAME,SM_ISIN
NSE,E,1333,EQUITY,HDFCBANK,1,,,,0.05,HDFCBANK,INE040A01034
NSE,D,35001,FUTIDX,NIFTY-Jun2026-FUT,75,2026-06-25,,,0.05,NIFTY,
NSE,D,35002,OPTIDX,NIFTY-Jun2026-24500-CE,75,2026-06-25,24500,CE,0.05,NIFTY,
NSE,I,13,INDEX,NIFTY,1,,,,0.05,NIFTY,
"""


def test_parse_dhan_csv_basic() -> None:
    rows = parse_dhan_csv(SAMPLE_CSV.encode())
    assert len(rows) == 4

    by_sym = {r["trading_symbol"]: r for r in rows}
    assert by_sym["HDFCBANK"]["exchange_segment"] == "NSE_EQ"
    assert by_sym["HDFCBANK"]["lot_size"] == 1
    assert by_sym["HDFCBANK"]["isin"] == "INE040A01034"

    fut = by_sym["NIFTY-Jun2026-FUT"]
    assert fut["exchange_segment"] == "NSE_FNO"
    assert fut["instrument_type"] == "FUTIDX"
    assert fut["lot_size"] == 75
    assert fut["expiry"] is not None and fut["expiry"].year == 2026

    opt = by_sym["NIFTY-Jun2026-24500-CE"]
    assert opt["option_type"] == "CE"
    assert opt["strike"] == Decimal("24500")
    assert opt["underlying"] == "NIFTY"

    idx = by_sym["NIFTY"]
    assert idx["exchange_segment"] == "IDX_I"


def test_parse_skips_rows_missing_security_id() -> None:
    csv = SAMPLE_CSV + "NSE,E,,EQUITY,BAD,1,,,,0.05,BAD,\n"
    rows = parse_dhan_csv(csv.encode())
    assert all(r["security_id"] for r in rows)
    assert len(rows) == 4


def test_parse_skips_unknown_segment() -> None:
    csv = "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SM_SYMBOL_NAME,SM_ISIN\nXXX,Z,99,EQUITY,GHOST,1,,,,0.05,GHOST,\n"
    rows = parse_dhan_csv(csv.encode())
    assert rows == []
