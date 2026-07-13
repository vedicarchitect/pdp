"""Per-day entry→exit trade ledger derived from strategy events.

Pairs each `leg_open` with its terminal close event by `security_id` in time
order. `stop_half` produces a partial row; the remaining lots pair to the later
terminal close. Still-open legs are returned with null exit fields.

No new Mongo/PG store — the ledger is a read-time pairing over existing events.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog

log = structlog.get_logger()
_IST = ZoneInfo("Asia/Kolkata")
_UTC = timezone.utc

# Event types that represent a terminal leg close (entry → exit match)
_TERMINAL_CLOSE_TYPES = frozenset(
    {
        "leg_close",
        "take_profit",
        "stop_all",
    }
)
# Partial close event
_PARTIAL_CLOSE_TYPE = "stop_half"
# Open event
_OPEN_TYPE = "leg_open"
# Every event type the ledger pairs — used to scope the Mongo query.
_LEDGER_EVENT_TYPES = _TERMINAL_CLOSE_TYPES | {_PARTIAL_CLOSE_TYPE, _OPEN_TYPE}

# Cache of parsed events keyed by (path, mtime_ns, size), so a repeated poll
# against an unchanged file (the common case — most polls land between two
# strategy events) skips the full disk read + re-parse. The log is append-only
# (StrategyDailyLog only ever opens in "a" mode), so mtime+size uniquely
# identify the exact set of lines already parsed.
_events_cache: dict[tuple[str, int, int], list[dict[str, Any]]] = {}


async def read_durable_day_events(
    strategy_id: str,
    day: date,
    *,
    mongo_db: Any = None,
    logs_dir: Path = Path("logs"),
) -> list[dict[str, Any]]:
    """Read strategy events for a given IST day from the durable store.

    Primary source: the Mongo ``events`` collection (survives process restarts and works
    across stateless API replicas, unlike the local JSONL log). Falls back to the JSONL log
    file when ``mongo_db`` isn't passed, Mongo is unavailable, or the collection has no rows
    for this day (pre-migration days, or a fresh deployment whose events haven't landed yet).

    Args:
        strategy_id: The strategy identifier (matches the ``strategy_id`` field written by
            ``DirectionalStrangle._emit_event``).
        day: The IST date whose events to read.
        mongo_db: The shared Motor database handle (``app.state.mongo_db``). Optional so
            callers without a Mongo connection (tests, scripts) still get the JSONL behavior.
        logs_dir: Directory root for the JSONL fallback files.
    """
    if mongo_db is not None:
        events = await _read_mongo_day_events(mongo_db, strategy_id, day)
        if events:
            return events
    return read_day_events(strategy_id, day, logs_dir=logs_dir)


async def _read_mongo_day_events(mongo_db: Any, strategy_id: str, day: date) -> list[dict[str, Any]]:
    """Query the durable ``events`` collection for one IST day's leg-open/close events."""
    start_ist = datetime(day.year, day.month, day.day, tzinfo=_IST)
    end_ist = datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=_IST)
    query = {
        "strategy_id": strategy_id,
        "event_type": {"$in": list(_LEDGER_EVENT_TYPES)},
        "ts": {"$gte": start_ist.astimezone(_UTC), "$lte": end_ist.astimezone(_UTC)},
    }
    try:
        cursor = mongo_db["events"].find(query, sort=[("ts", 1)])
        out: list[dict[str, Any]] = []
        async for doc in cursor:
            doc.pop("_id", None)
            ts = doc.get("ts")
            if ts is not None and hasattr(ts, "isoformat"):
                doc["ts"] = ts.isoformat()
            out.append(doc)
        return out
    except Exception as exc:
        log.warning("trade_ledger_mongo_read_failed", strategy_id=strategy_id, day=str(day), exc=str(exc))
        return []


def read_day_events(strategy_id: str, day: date, *, logs_dir: Path = Path("logs")) -> list[dict[str, Any]]:
    """Read strategy events for a given IST day from the JSONL log file.

    Falls back to an empty list if the log file doesn't exist (OpenSearch
    fallback can be added later). Cached by file mtime+size — an unchanged
    file returns the previously-parsed list without touching disk again.
    """
    path = logs_dir / strategy_id / f"{day.isoformat()}.log"
    try:
        st = path.stat()
    except FileNotFoundError:
        log.debug("trade_ledger_no_logfile", strategy_id=strategy_id, day=str(day))
        return []

    cache_key = (str(path), st.st_mtime_ns, st.st_size)
    cached = _events_cache.get(cache_key)
    if cached is not None:
        return cached

    events: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Only cache today's (or an already-closed prior day's) result under this
    # exact (mtime, size) key — a subsequent append changes the key naturally,
    # so stale entries are never served; drop older keys for this path to keep
    # the cache from growing unboundedly across a long session.
    stale = [k for k in _events_cache if k[0] == str(path) and k != cache_key]
    for k in stale:
        del _events_cache[k]
    _events_cache[cache_key] = events
    return events


def pair_trades(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair `leg_open` events with their terminal close events by security_id.

    Returns a list of round-trip rows, each with full entry→exit economics.
    A `stop_half` produces a partial row (partial=True); the remaining lots
    match to the later terminal close. Still-open legs get exit_price=None.
    """
    # Collect opens by security_id (FIFO queue)
    opens_by_sid: dict[str, list[dict[str, Any]]] = {}
    close_events: list[dict[str, Any]] = []

    for evt in events:
        etype = evt.get("event_type", "")
        if etype == _OPEN_TYPE:
            sid = evt.get("sid", "")
            opens_by_sid.setdefault(sid, []).append(evt)
        elif etype in _TERMINAL_CLOSE_TYPES or etype == _PARTIAL_CLOSE_TYPE:
            close_events.append(evt)

    rows: list[dict[str, Any]] = []

    for close_evt in close_events:
        sid = close_evt.get("sid", "")
        etype = close_evt.get("event_type", "")
        is_partial = etype == _PARTIAL_CLOSE_TYPE

        open_list = opens_by_sid.get(sid, [])
        if not open_list:
            # Close without a matching open — emit a best-effort row from close fields
            rows.append(_build_row(close_evt=close_evt, is_partial=is_partial))
            continue

        open_evt = open_list[0]

        # For a partial close, don't consume the open — it stays for the terminal close
        # For a terminal close, consume the open
        if not is_partial:
            open_list.pop(0)

        rows.append(_build_row(open_evt=open_evt, close_evt=close_evt, is_partial=is_partial))

    # Remaining opens with no matching close → still-open legs
    for remaining_opens in opens_by_sid.values():
        for open_evt in remaining_opens:
            rows.append(_build_row(open_evt=open_evt))

    return rows


def group_by_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group paired rows by underlying index."""
    by_index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        underlying = row.get("underlying", "UNKNOWN")
        by_index.setdefault(underlying, []).append(row)
    return by_index


def compute_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute totals across all closed rows."""
    realized_pnl = 0.0
    n_round_trips = 0
    n_open = 0
    for row in rows:
        if row.get("open"):
            n_open += 1
        elif row.get("pnl") is not None:
            realized_pnl += row["pnl"]
            if not row.get("partial"):
                n_round_trips += 1
    return {
        "realized_pnl": round(realized_pnl, 2),
        "n_round_trips": n_round_trips,
        "n_open": n_open,
    }


def _first_not_none(*values: Any) -> Any:
    """Return the first value that is not None (falsy-but-valid values like 0
    or '' are kept, unlike an `or` chain)."""
    for v in values:
        if v is not None:
            return v
    return None


def _build_row(
    *,
    open_evt: dict[str, Any] | None = None,
    close_evt: dict[str, Any] | None = None,
    is_partial: bool = False,
) -> dict[str, Any]:
    """Build one ledger row from an open event, a close event, or both.

    - `open_evt` + `close_evt`: a paired round-trip (or partial) row.
    - `close_evt` only: a close with no matching open (best-effort row).
    - `open_evt` only: a still-open leg (null exit fields).
    Shared fields prefer `close_evt` when both are present (its values are the
    authoritative close-time snapshot); falls back to `open_evt`. Uses an
    explicit not-None check rather than `or` so a legitimate `0` (e.g. strike
    or lots) is never silently overridden by the other event's value.
    """
    o = open_evt or {}
    c = close_evt or {}
    is_open = close_evt is None
    return {
        "underlying": _first_not_none(c.get("underlying"), o.get("underlying")),
        "security_id": _first_not_none(c.get("sid"), o.get("sid")),
        "symbol": _first_not_none(c.get("symbol"), o.get("symbol")),
        "opt_type": _first_not_none(c.get("opt_type"), o.get("opt_type")),
        "strike": _first_not_none(c.get("strike"), o.get("strike")),
        "expiry": _first_not_none(c.get("expiry"), o.get("expiry")),
        "lots": _first_not_none(c.get("lots"), o.get("lots")),
        "is_hedge": _first_not_none(c.get("is_hedge"), o.get("is_hedge"), False),
        "entry_price": _first_not_none(c.get("entry_price"), o.get("entry_price")),
        "entry_time": _first_not_none(c.get("entry_time"), o.get("entry_time")),
        "exit_price": c.get("exit_price"),
        "exit_time": c.get("exit_time"),
        "pnl": c.get("pnl"),
        "reason": _first_not_none(c.get("reason"), c.get("event_type")) if close_evt else None,
        "partial": is_partial,
        "open": is_open,
    }
