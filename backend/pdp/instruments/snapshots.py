"""Daily filtered scrip-master snapshots.

Dhan's scrip master lists only *currently active* contracts, so once a weekly/monthly
option expires its row vanishes — and a backtest of a past date can no longer resolve the
expired contract's ``security_id``. This module persists a small, date-stamped snapshot of
the master each trading day, **filtered to a configured set of underlyings** (default
NIFTY / BANKNIFTY / SENSEX, plus their index rows). A historical lookup then returns the
snapshot taken on or before a target date.

Snapshots are flat CSVs at ``<masters_dir>/<YYYY-MM-DD>.csv`` (default ``data/masters/``),
one per trading day, written idempotently (re-running a day overwrites it).
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# Default scope — intentionally narrow "as of now"; widen via settings without code changes.
DEFAULT_SNAPSHOT_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "SENSEX")
DEFAULT_MASTERS_DIR = Path("data/masters")

# Index (IDX_I) instruments carry no `underlying`; match them by trading-symbol alias.
_INDEX_ALIASES: dict[str, set[str]] = {
    "NIFTY": {"NIFTY", "NIFTY50", "NIFTY 50"},
    "BANKNIFTY": {"BANKNIFTY", "NIFTY BANK", "NIFTYBANK"},
    "SENSEX": {"SENSEX", "BSE SENSEX", "BSESENSEX"},
}

# Column order written to / read from the snapshot CSV (matches parse_dhan_csv keys).
FIELDS: tuple[str, ...] = (
    "security_id",
    "exchange_segment",
    "trading_symbol",
    "instrument_type",
    "underlying",
    "expiry",
    "strike",
    "option_type",
    "lot_size",
    "tick_size",
    "isin",
)


def _norm(value: Any) -> str:
    return str(value).strip().upper() if value is not None else ""


def parse_underlyings(raw: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Parse the SNAPSHOT_UNDERLYINGS setting (JSON list string) into a tuple."""
    if isinstance(raw, (list, tuple)):
        return tuple(_norm(u) for u in raw)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return DEFAULT_SNAPSHOT_UNDERLYINGS
    if isinstance(parsed, list):
        return tuple(_norm(u) for u in parsed)
    return DEFAULT_SNAPSHOT_UNDERLYINGS


def _matches(row: dict[str, Any], underlyings: tuple[str, ...]) -> bool:
    """True if a parsed master row belongs to one of the allowed underlyings.

    Keeps every derivative whose ``underlying`` is in the set, plus the index (IDX_I)
    instruments for those underlyings (matched by trading-symbol alias).
    """
    if _norm(row.get("underlying")) in underlyings:
        return True
    if row.get("exchange_segment") == "IDX_I":
        sym = _norm(row.get("trading_symbol"))
        sym_ns = sym.replace(" ", "")
        for base in underlyings:
            aliases = _INDEX_ALIASES.get(base, {base})
            if sym in aliases or sym_ns in {a.replace(" ", "") for a in aliases}:
                return True
    return False


def filter_for_underlyings(
    rows: list[dict[str, Any]],
    underlyings: tuple[str, ...] = DEFAULT_SNAPSHOT_UNDERLYINGS,
) -> list[dict[str, Any]]:
    """Keep only rows belonging to the allowed underlyings (+ their index rows)."""
    allowed = tuple(_norm(u) for u in underlyings)
    return [r for r in rows if _matches(r, allowed)]


def snapshot_path(snapshot_date: date, masters_dir: Path = DEFAULT_MASTERS_DIR) -> Path:
    return Path(masters_dir) / f"{snapshot_date.isoformat()}.csv"


def _to_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def write_snapshot(
    rows: list[dict[str, Any]],
    snapshot_date: date,
    masters_dir: Path = DEFAULT_MASTERS_DIR,
) -> Path:
    """Write ``rows`` to ``<masters_dir>/<date>.csv`` (idempotent overwrite)."""
    path = snapshot_path(snapshot_date, masters_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _to_cell(row.get(k)) for k in FIELDS})
    log.info("instrument_snapshot_written", date=snapshot_date.isoformat(), rows=len(rows), path=str(path))
    return path


def create_snapshot(
    master_rows: list[dict[str, Any]],
    snapshot_date: date,
    masters_dir: Path = DEFAULT_MASTERS_DIR,
    underlyings: tuple[str, ...] = DEFAULT_SNAPSHOT_UNDERLYINGS,
) -> tuple[Path, int]:
    """Filter parsed master rows to the allowed underlyings and write the day's snapshot."""
    filtered = filter_for_underlyings(master_rows, underlyings)
    path = write_snapshot(filtered, snapshot_date, masters_dir)
    return path, len(filtered)


def list_snapshot_dates(masters_dir: Path = DEFAULT_MASTERS_DIR) -> list[date]:
    """All snapshot dates present in ``masters_dir``, ascending."""
    directory = Path(masters_dir)
    if not directory.exists():
        return []
    dates: list[date] = []
    for p in directory.glob("*.csv"):
        try:
            dates.append(date.fromisoformat(p.stem))
        except ValueError:
            continue
    return sorted(dates)


def latest_snapshot_on_or_before(
    target: date, masters_dir: Path = DEFAULT_MASTERS_DIR
) -> date | None:
    """The most recent snapshot date ≤ ``target``, or None if there is none."""
    candidates = [d for d in list_snapshot_dates(masters_dir) if d <= target]
    return candidates[-1] if candidates else None


def load_master_for_date(
    target: date, masters_dir: Path = DEFAULT_MASTERS_DIR
) -> list[dict[str, Any]]:
    """Load the snapshot taken on or before ``target`` as a list of row dicts.

    Raises ``FileNotFoundError`` when no snapshot exists on or before the date, so the
    caller can fall back to the expired-options warehouse.
    """
    snap_date = latest_snapshot_on_or_before(target, masters_dir)
    if snap_date is None:
        raise FileNotFoundError(
            f"no instrument snapshot on or before {target.isoformat()} in {masters_dir}"
        )
    path = snapshot_path(snap_date, masters_dir)
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def resolve_instrument(
    rows: list[dict[str, Any]],
    *,
    underlying: str,
    option_type: str | None = None,
    strike: float | None = None,
    expiry: date | None = None,
    exchange_segment: str | None = None,
) -> dict[str, Any] | None:
    """Find a single snapshot row matching the given criteria (first match, or None)."""
    want_underlying = _norm(underlying)
    want_option = _norm(option_type) if option_type else None
    want_expiry = expiry.isoformat() if expiry else None
    for row in rows:
        if _norm(row.get("underlying")) != want_underlying:
            continue
        if want_option is not None and _norm(row.get("option_type")) != want_option:
            continue
        if exchange_segment is not None and row.get("exchange_segment") != exchange_segment:
            continue
        if want_expiry is not None and (row.get("expiry") or "") != want_expiry:
            continue
        if strike is not None:
            cell = row.get("strike") or ""
            if cell == "" or float(cell) != float(strike):
                continue
        return row
    return None
