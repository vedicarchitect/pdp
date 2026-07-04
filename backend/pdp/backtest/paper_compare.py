"""Generic, strategy_id-keyed backtest-vs-paper comparison.

Supersedes the SuperTrend-only, single-date `backtest/compare.py` CLI. Reads paper realized
P&L from the PostgreSQL ledger (source of truth for fills), aligns it against a backtest
run's per-day series from Mongo `backtest_days`, and diffs decision events minute-by-minute
using one shared vocabulary that both the backtest (`backtest_decisions`, from
`backtest-decision-trace`) and the live strategy (`pdp.strategy.log.StrangleEventType`) map
onto. Divergence is annotated by cross-referencing the data-coverage gap radar
(`pdp.warehouse.coverage`) — a concrete cause is attributed only when one exists.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.journal.stats import compute_daily_stats
from pdp.orders.models import Order, Trade

_IST = timedelta(hours=5, minutes=30)


def _ist_date(ts: datetime) -> date:
    ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return (ts + _IST).date()


def _ist_window_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """[lo, hi) in UTC covering the IST trade-window [date_from, date_to] inclusive."""
    lo = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC) - _IST
    hi = datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) - _IST + timedelta(days=1)
    return lo, hi


# ── 1. Per-strategy paper realized P&L (PostgreSQL ledger) ─────────────────────


async def fetch_paper_trades(
    session: AsyncSession, date_from: date, date_to: date, strategy_id: str | None = None,
) -> list[dict[str, Any]]:
    """PAPER-mode trades joined to their orders over an IST date window.

    Generic over `strategy_id` — pass `None` to fetch every strategy at once.
    """
    lo, hi = _ist_window_bounds(date_from, date_to)
    stmt = (
        select(
            Order.strategy_id,
            Trade.security_id,
            Trade.side,
            Trade.qty,
            Trade.fill_price,
            Trade.charges,
            Trade.filled_at,
        )
        .join(Order, Trade.order_id == Order.id)
        .where(Order.mode == "PAPER", Trade.filled_at >= lo, Trade.filled_at < hi)
        .order_by(Trade.filled_at)
    )
    if strategy_id:
        stmt = stmt.where(Order.strategy_id == strategy_id)
    result = await session.execute(stmt)
    return [
        {
            "strategy_id": strat_id,
            "security_id": sid,
            "side": side,
            "qty": qty,
            "fill_price": fill_price,
            "charges": charges,
            "filled_at": filled_at,
        }
        for strat_id, sid, side, qty, fill_price, charges, filled_at in result.all()
    ]


def group_paper_pnl(trades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group PAPER trades by `strategy_id` then IST trade-date, computing realized P&L per
    day with the same semantics as `pdp.journal.stats.compute_daily_stats`. Returns both
    gross (pre-charges `net_premium`) and net (post-charges `realized_pnl`) per day so a
    charge-model mismatch against the backtest is visible rather than hidden."""
    by_strategy: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for t in trades:
        strat = t.get("strategy_id") or "unassigned"
        d = _ist_date(t["filled_at"]).isoformat()
        by_strategy.setdefault(strat, {}).setdefault(d, []).append(t)

    out: dict[str, list[dict[str, Any]]] = {}
    for strat, by_date in by_strategy.items():
        days: list[dict[str, Any]] = []
        for d in sorted(by_date):
            stats = compute_daily_stats(by_date[d])
            days.append({
                "date": d,
                "gross_pnl": stats["net_premium"],
                "net_pnl": stats["realized_pnl"],
                "total_charges": stats["total_charges"],
                "round_trips": stats["round_trips"],
                "wins": stats["wins"],
                "losses": stats["losses"],
            })
        out[strat] = days
    return out


async def paper_pnl_by_strategy(
    session: AsyncSession, date_from: date, date_to: date, strategy_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Realized P&L per `strategy_id`, grouped by IST trade date, from PAPER trades only."""
    trades = await fetch_paper_trades(session, date_from, date_to, strategy_id)
    return group_paper_pnl(trades)


def resolve_live_strategy_id(run: dict[str, Any]) -> str | None:
    """Map a backtest run to its live/paper `strategy_id` via the unified strategy registry.

    Delegates to `pdp.strategy.unified_registry.canonical_id`, which looks up the matching
    live `strategies/*.yaml` entry by family + underlying instead of hardcoding the
    `directional_strangle_<underlying>` naming scheme.
    """
    from pdp.strategy.unified_registry import canonical_id

    underlying = (run.get("config") or {}).get("underlying")
    return canonical_id(run.get("strategy_id"), underlying)


# ── 2. vs-paper per-day alignment ───────────────────────────────────────────────


def align_days(
    backtest_days: list[dict[str, Any]],
    paper_days: list[dict[str, Any]],
    *,
    tolerance: float = 0.0,
) -> list[dict[str, Any]]:
    """Align a backtest run's per-day `net` series against paper `net_pnl` by date.

    Divergence is only computed for dates present on both sides — a date where paper simply
    has no data yet (e.g. before paper went live) is not itself a divergence.
    """
    bt_by_date = {d["date"]: d for d in backtest_days}
    paper_by_date = {d["date"]: d for d in paper_days}
    rows: list[dict[str, Any]] = []
    for d in sorted(set(bt_by_date) | set(paper_by_date)):
        bt = bt_by_date.get(d)
        pd = paper_by_date.get(d)
        bt_net = bt.get("net") if bt else None
        paper_net = pd.get("net_pnl") if pd else None
        if bt_net is None or paper_net is None:
            divergence = None
            diverges = False
        else:
            divergence = round(bt_net - paper_net, 2)
            diverges = abs(divergence) > tolerance
        rows.append({
            "date": d,
            "backtest_net": bt_net,
            "paper_net": paper_net,
            "divergence": divergence,
            "diverges": diverges,
        })
    return rows


# ── 3. Shared decision-event vocabulary + adapter ───────────────────────────────

# Closed vocabulary both the backtest (`backtest_decisions`, from `backtest-decision-trace`)
# and the live strangle event log (`pdp.strategy.log.StrangleEventType`) normalize onto.
DECISION_VOCAB = ("bias", "entry", "scale_in", "rollup", "exit", "reentry", "stop_gate_wait")

_BACKTEST_EVENT_MAP: dict[str, str] = {
    "st_flip": "bias",
    "entry": "entry",
    "scale_in": "scale_in",
    "rollup": "rollup",
    "exit": "exit",
    "reentry": "reentry",
}

# `leg_status` is a heartbeat (no decision) and is deliberately excluded.
_LIVE_EVENT_MAP: dict[str, str] = {
    "bias_evaluated": "bias",
    "bucket_change": "bias",
    "leg_open": "entry",
    "rolled": "rollup",
    "leg_close": "exit",
    "take_profit": "exit",
    "stop_half": "exit",
    "stop_all": "exit",
    "day_loss_cap": "exit",
    "square_off": "exit",
    "stop_gate_wait": "stop_gate_wait",
}


def normalize_backtest_event(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Map one `backtest_decisions` doc onto the shared vocabulary; `None` if unmapped."""
    action = _BACKTEST_EVENT_MAP.get(str(doc.get("event", "")))
    if action is None:
        return None
    ts = doc.get("ts_ist")
    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    return {
        "side": "backtest",
        "ts_ist": ts_str,
        "minute": ts_str[:16],
        "action": action,
        "sub_reason": doc.get("sub_reason"),
        "snapshot": doc.get("snapshot") or {},
    }


def normalize_live_event(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Map one live `pdp-strangle-events-*` doc onto the shared vocabulary; `None` if unmapped."""
    action = _LIVE_EVENT_MAP.get(str(doc.get("event_type", "")).lower())
    if action is None:
        return None
    ts_str = str(doc.get("ist_time", ""))
    snapshot = {
        "spot": doc.get("spot"),
        "score": doc.get("score"),
        "bucket": doc.get("bucket"),
        "bias_votes": doc.get("bias_votes"),
        "day_pnl": doc.get("day_pnl"),
    }
    return {
        "side": "live",
        "ts_ist": ts_str,
        "minute": ts_str[:16],
        "action": action,
        "sub_reason": doc.get("reason"),
        "snapshot": snapshot,
    }


# ── 4. Minute-level decision diff ───────────────────────────────────────────────


def minute_diff(
    backtest_docs: list[dict[str, Any]], live_docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join backtest and live decision events by IST minute, flagging action mismatches."""
    by_minute: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for doc in backtest_docs:
        norm = normalize_backtest_event(doc)
        if norm is None:
            continue
        by_minute.setdefault(norm["minute"], {"backtest": [], "live": []})["backtest"].append(norm)
    for doc in live_docs:
        norm = normalize_live_event(doc)
        if norm is None:
            continue
        by_minute.setdefault(norm["minute"], {"backtest": [], "live": []})["live"].append(norm)

    rows: list[dict[str, Any]] = []
    for minute in sorted(by_minute):
        bt = by_minute[minute]["backtest"]
        lv = by_minute[minute]["live"]
        rows.append({
            "minute": minute,
            "backtest": bt,
            "live": lv,
            "mismatch": {e["action"] for e in bt} != {e["action"] for e in lv},
        })
    return rows


# ── 5. Divergence root-causing ──────────────────────────────────────────────────


def annotate_day_divergence(
    days: list[dict[str, Any]], radar: dict[str, dict[str, str]] | None,
) -> list[dict[str, Any]]:
    """Attach a `cause` to diverging days by cross-referencing the gap radar (change 2).

    Attribution is factual, not inferred: a concrete cause is only attached when the radar
    reports a missing input family for that date; otherwise `cause` stays `None`.
    """
    radar = radar or {}
    for row in days:
        if not row.get("diverges"):
            row["cause"] = None
            continue
        day_radar = radar.get(row["date"], {})
        missing = [label for label in day_radar.values() if label != "ready"]
        row["cause"] = missing[0] if missing else None
    return days


def annotate_minute_divergence(
    rows: list[dict[str, Any]], radar: dict[str, dict[str, str]] | None,
) -> list[dict[str, Any]]:
    """Attach a `cause` to mismatched minutes: a missing gap-radar input first, else an
    absent bias-vote signal found on either side's snapshot."""
    radar = radar or {}
    for row in rows:
        if not row.get("mismatch"):
            row["cause"] = None
            continue
        day_radar = radar.get(row["minute"][:10], {})
        missing = [label for label in day_radar.values() if label != "ready"]
        if missing:
            row["cause"] = missing[0]
            continue
        votes: dict[str, Any] = {}
        for e in row.get("live", []) + row.get("backtest", []):
            snap = e.get("snapshot") or {}
            v = snap.get("bias_votes") or snap.get("votes")
            if v:
                votes = v
                break
        absent = [k for k, v in votes.items() if v is None]
        row["cause"] = f"vote missing: {absent[0]}" if absent else None
    return rows
