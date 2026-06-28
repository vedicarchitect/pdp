"""Pure mappers: domain payload → (typed index document, idempotent doc id).

Each emit site keeps its existing durable write (JSONL / Mongo) and additionally enqueues
the typed doc via the active indexer. Mappers never touch OpenSearch — they just shape
documents, so they are trivially unit-testable.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# index family constants (full monthly name resolved by the indexer)
STRANGLE_EVENTS = "strangle-events"
TRADES = "trades"
JOURNAL = "journal"
BACKTEST_RUNS = "backtest-runs"
BACKTEST_DAYS = "backtest-days"
BACKTEST_TRADES = "backtest-trades"

_EVENT_FIELDS = (
    "event_type", "strategy_id", "account_id", "snapshot_date", "ist_time",
    "underlying", "spot", "score", "bucket", "sid", "opt_type", "strike",
    "lots", "entry_price", "exit_price", "leg_pnl", "day_pnl", "reason",
    "bias_votes", "note",
)


def strangle_event_doc(record: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Map a `StrategyDailyLog` JSONL record → strangle-events doc + id."""
    doc: dict[str, Any] = {k: record.get(k) for k in _EVENT_FIELDS if k in record}
    doc["@timestamp"] = record.get("ist_time") or record.get("timestamp")
    sid = record.get("sid", "")
    doc_id = (
        f"{record.get('strategy_id', '')}:{record.get('ist_time', '')}:"
        f"{record.get('event_type', '')}:{sid}"
    )
    return doc, doc_id


def fill_doc(entry: dict[str, Any], *, mode: str = "paper") -> tuple[dict[str, Any], str | None]:
    """Map a journal fill entry → trades doc (auto id)."""
    doc = {
        "@timestamp": entry.get("ts") or datetime.now(UTC).isoformat(),
        "security_id": entry.get("security_id", ""),
        "side": entry.get("side", ""),
        "qty": _int(entry.get("qty")),
        "fill_price": _float(entry.get("fill_price")),
        "charges": _float(entry.get("charges")),
        "strategy_id": entry.get("strategy_id"),
        "mode": mode,
    }
    return doc, None


def journal_day_doc(
    day: str, stats: dict[str, Any], *, mode: str = "paper"
) -> tuple[dict[str, Any], str]:
    """Map a journal daily rollup → journal doc + id (one per day+mode)."""
    doc = {
        "@timestamp": day,
        "date": day,
        "mode": mode,
        "round_trips": _int(stats.get("round_trips")),
        "wins": _int(stats.get("wins")),
        "losses": _int(stats.get("losses")),
        "realized_pnl": _float(stats.get("realized_pnl")),
        "gross_premium_sold": _float(stats.get("gross_premium_sold")),
        "gross_premium_bought": _float(stats.get("gross_premium_bought")),
    }
    return doc, f"{day}:{mode}"


def backtest_run_doc(run: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Map a `build_run_doc` result → backtest-runs doc + id (run_id)."""
    created = run.get("created_at")
    created_iso = created.isoformat() if hasattr(created, "isoformat") else created
    doc = {
        "@timestamp": created_iso,
        "run_id": run.get("run_id"),
        "kind": run.get("kind"),
        "strategy_id": run.get("strategy_id"),
        "window": run.get("window"),
        "metrics": run.get("metrics"),
        "verdict": run.get("verdict"),
        "promotion_state": run.get("promotion_state"),
        "git_sha": run.get("git_sha"),
        "created_at": created_iso,
        "config": run.get("config"),
    }
    return doc, str(run.get("run_id"))


def backtest_day_doc(day: dict[str, Any]) -> tuple[dict[str, Any], str]:
    doc = {"@timestamp": day.get("date"), **day}
    return doc, f"{day.get('run_id')}:{day.get('date')}"


def backtest_trade_doc(trade: dict[str, Any]) -> tuple[dict[str, Any], str]:
    doc = {"@timestamp": trade.get("date"), **trade}
    return doc, f"{trade.get('run_id')}:{trade.get('date')}"


def _float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int:
    try:
        return int(v) if v not in (None, "") else 0
    except (TypeError, ValueError):
        return 0
