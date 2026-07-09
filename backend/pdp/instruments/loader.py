from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.instruments.models import Instrument

log = structlog.get_logger()

BATCH_SIZE = 2000  # asyncpg caps query params at 32767; 2000 rows × 11 cols = 22k

# Maps Dhan's `EXCH_ID` + `SEGMENT` codes → our canonical exchange-segment.
SEGMENT_MAP: dict[tuple[str, str], str] = {
    ("NSE", "E"): "NSE_EQ",
    ("NSE", "D"): "NSE_FNO",
    ("NSE", "C"): "NSE_CUR",
    ("NSE", "I"): "IDX_I",
    ("BSE", "E"): "BSE_EQ",
    ("BSE", "D"): "BSE_FNO",
    ("BSE", "C"): "BSE_CUR",
    ("BSE", "I"): "IDX_I",
    ("MCX", "M"): "MCX_COMM",
}


def _g(row: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-empty value among `keys` from a CSV row."""
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            if v == "" or v == "NA":
                continue
        return v
    return None


@dataclass(slots=True)
class LoadStats:
    rows_seen: int = 0
    rows_upserted: int = 0


def _normalize_segment(exch: str | None, seg: str | None) -> str | None:
    if not exch or not seg:
        return None
    return SEGMENT_MAP.get((exch.strip().upper(), seg.strip().upper()))


def _parse_date(value: Any) -> date | None:
    if value is None or value == "" or value == "NA":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "" or value == "NA":
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    return d if d != 0 else None


def parse_dhan_csv(source: bytes | str | Path) -> list[dict[str, Any]]:
    """Parse Dhan's api-scrip-master-detailed.csv → list of upsert-ready dicts."""
    if isinstance(source, (str, Path)) and Path(source).exists():
        df = pl.read_csv(Path(source), infer_schema_length=2000, ignore_errors=True)
    elif isinstance(source, bytes):
        df = pl.read_csv(BytesIO(source), infer_schema_length=2000, ignore_errors=True)
    else:
        df = pl.read_csv(BytesIO(str(source).encode()), infer_schema_length=2000, ignore_errors=True)

    rows: list[dict[str, Any]] = []
    for row in df.iter_rows(named=True):
        security_id = _g(row, "SECURITY_ID", "SEM_SMST_SECURITY_ID")
        if security_id is None:
            continue
        segment = _normalize_segment(
            _g(row, "EXCH_ID", "SEM_EXM_EXCH_ID"),
            _g(row, "SEGMENT", "SEM_SEGMENT"),
        )
        if segment is None:
            continue
        trading_symbol = _g(
            row,
            "SYMBOL_NAME",
            "DISPLAY_NAME",
            "SEM_TRADING_SYMBOL",
            "SEM_CUSTOM_SYMBOL",
        )
        if not trading_symbol:
            continue
        instrument_type = _g(row, "INSTRUMENT", "INSTRUMENT_TYPE", "SEM_INSTRUMENT_NAME") or "EQUITY"
        option_type = _g(row, "OPTION_TYPE", "SEM_OPTION_TYPE")
        if option_type in {"XX", "*"}:
            option_type = None
        rows.append(
            {
                "security_id": str(security_id).strip(),
                "exchange_segment": segment,
                "trading_symbol": str(trading_symbol).strip(),
                "instrument_type": str(instrument_type).strip(),
                "underlying": _g(row, "UNDERLYING_SYMBOL", "SM_SYMBOL_NAME"),
                "expiry": _parse_date(_g(row, "SM_EXPIRY_DATE", "SEM_EXPIRY_DATE")),
                "strike": _parse_decimal(_g(row, "STRIKE_PRICE", "SEM_STRIKE_PRICE")),
                "option_type": option_type,
                "lot_size": int(float(_g(row, "LOT_SIZE", "SEM_LOT_UNITS") or 1)),
                "freeze_qty": int(float(fq))
                if (fq := _g(row, "FREEZE_QTY", "SEM_FREEZE_QTY")) is not None
                else None,
                "tick_size": _parse_decimal(_g(row, "TICK_SIZE", "SEM_TICK_SIZE")) or Decimal("0.05"),
                "isin": _g(row, "ISIN", "SM_ISIN"),
            }
        )
    return rows


async def upsert_instruments(
    session: AsyncSession, rows: list[dict[str, Any]], batch_size: int = BATCH_SIZE
) -> LoadStats:
    stats = LoadStats(rows_seen=len(rows))
    if not rows:
        return stats
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        stmt = insert(Instrument).values(batch)
        update_cols = {
            c.name: stmt.excluded[c.name]
            for c in Instrument.__table__.columns
            if c.name not in {"id", "security_id", "exchange_segment"}
        }
        update_cols["updated_at"] = stmt.excluded.updated_at
        stmt = stmt.on_conflict_do_update(
            constraint="uq_instruments_secid_seg",
            set_=update_cols,
        )
        await session.execute(stmt)
        stats.rows_upserted += len(batch)
    await session.commit()
    return stats


async def download_dhan_master(url: str, timeout: float = 60.0) -> bytes:  # noqa: ASYNC109
    log.info("dhan_master_download_start", url=url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    log.info("dhan_master_download_done", bytes=len(resp.content))
    return resp.content


async def refresh_instruments(session: AsyncSession, url: str) -> LoadStats:
    raw = await download_dhan_master(url)
    rows = parse_dhan_csv(raw)
    log.info("dhan_master_parsed", rows=len(rows))
    return await upsert_instruments(session, rows)
