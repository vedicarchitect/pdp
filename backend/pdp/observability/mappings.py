"""Composable index templates for the universal log index + typed analytics indices.

`dynamic: false` keeps mappings stable — unknown fields are stored but not indexed
(except the universal index's `context`, a `flattened` catch-all). `ensure_templates()`
is idempotent and runs at app startup.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from opensearchpy import AsyncOpenSearch

log = structlog.get_logger("pdp.observability").bind(_no_ship=True)

_KW = {"type": "keyword"}
_DATE = {"type": "date"}
_DBL = {"type": "double"}
_INT = {"type": "integer"}
_TXT = {"type": "text"}

# family -> mapping properties. The full index pattern is "<prefix>-<family>-*".
_FAMILIES: dict[str, dict[str, Any]] = {
    "logs": {
        "@timestamp": _DATE,
        "source": _KW,
        "level": _KW,
        "logger": _KW,
        "event": _TXT,
        "service": _KW,
        "env": _KW,
        "request_id": _KW,
        "strategy_id": _KW,
        "screen": _KW,
        "build": _KW,
        "device": _KW,
        "exc": _TXT,
        "context": {"type": "flat_object"},
    },
    "strangle-events": {
        "@timestamp": _DATE,
        "event_type": _KW,
        "strategy_id": _KW,
        "account_id": _KW,
        "snapshot_date": _DATE,
        "ist_time": _DATE,
        "underlying": _KW,
        "spot": _DBL,
        "score": _DBL,
        "bucket": _KW,
        "sid": _KW,
        "opt_type": _KW,
        "strike": _DBL,
        "lots": _INT,
        "entry_price": _DBL,
        "exit_price": _DBL,
        "leg_pnl": _DBL,
        "day_pnl": _DBL,
        "reason": _KW,
        "bias_votes": {"type": "object", "enabled": True},
        "note": _TXT,
    },
    "trades": {
        "@timestamp": _DATE,
        "security_id": _KW,
        "symbol": _KW,
        "side": _KW,
        "qty": _INT,
        "fill_price": _DBL,
        "charges": _DBL,
        "strategy_id": _KW,
        "mode": _KW,
        "opt_type": _KW,
        "strike": _DBL,
        "realized_pnl": _DBL,
        "round_trip_id": _KW,
    },
    "journal": {
        "@timestamp": _DATE,
        "date": _DATE,
        "mode": _KW,
        "strategy_id": _KW,
        "round_trips": _INT,
        "wins": _INT,
        "losses": _INT,
        "realized_pnl": _DBL,
        "gross_premium_sold": _DBL,
        "gross_premium_bought": _DBL,
    },
    "backtest-runs": {
        "@timestamp": _DATE,
        "run_id": _KW,
        "kind": _KW,
        "strategy_id": _KW,
        "sweep_id": _KW,
        "window": {"properties": {"from": _DATE, "to": _DATE}},
        "metrics": {
            "properties": {
                "net": _DBL,
                "profit_factor": _DBL,
                "win_rate": _DBL,
                "max_dd": _DBL,
                "sharpe": _DBL,
                "calmar": _DBL,
                "trades": _INT,
                "halted": _INT,
                "days": _INT,
            }
        },
        "verdict": _KW,
        "promotion_state": _KW,
        "git_sha": _KW,
        "created_at": _DATE,
        "config": {"type": "flat_object"},
        "param_grid": {"type": "flat_object"},
    },
    "backtest-days": {
        "@timestamp": _DATE,
        "run_id": _KW,
        "date": _DATE,
        "net": _DBL,
        "gross_pnl": _DBL,
        "commission": _DBL,
        "cum_equity": _DBL,
        "drawdown": _DBL,
        "nifty_chg": _DBL,
        "trades": _INT,
        "halted": _KW,
    },
    "backtest-trades": {
        "@timestamp": _DATE,
        "run_id": _KW,
        "date": _DATE,
        "fills": {
            "type": "nested",
            "properties": {
                "time": _KW,
                "side": _KW,
                "opt_type": _KW,
                "strike": _DBL,
                "qty": _INT,
                "price": _DBL,
                "leg_pnl": _DBL,
                "day_pnl": _DBL,
                "commission": _DBL,
            },
        },
    },
    "backtest-decisions": {
        "@timestamp": _DATE,
        "run_id": _KW,
        "strategy_id": _KW,
        "date": _DATE,
        "ts_ist": _DATE,
        "event": _KW,
        "sub_reason": _KW,
        "action": _KW,
        "snapshot": {"type": "flat_object"},
    },
    "backtest-promotions": {
        "@timestamp": _DATE,
        "run_id": _KW,
        "source_run_id": _KW,
        "strategy_id": _KW,
        "verdict": _KW,
        "yaml_path": _KW,
        "note": _TXT,
        "promoted_at": _DATE,
        "stitched_oos": {"type": "flat_object"},
        "verdict_breakdown": {"type": "flat_object"},
    },
    "data-coverage": {
        "@timestamp": _DATE,
        "underlying": _KW,
        "family": _KW,
        "min_date": _DATE,
        "max_date": _DATE,
        "covered_days": _INT,
        "total_days": _INT,
        "coverage_pct": _DBL,
        "gap_days": _INT,
        "gap_ranges": _KW,
    },
}


async def ensure_templates(client: AsyncOpenSearch, prefix: str = "pdp") -> int:
    """Register/update one composable index template per family. Idempotent."""
    count = 0
    for family, properties in _FAMILIES.items():
        name = f"{prefix}-{family}"
        body = {
            "index_patterns": [f"{name}-*"],
            "template": {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {"dynamic": False, "properties": properties},
            },
        }
        try:
            await client.indices.put_index_template(name=name, body=body)
            count += 1
        except Exception as exc:  # noqa: BLE001 — bootstrap must not crash startup
            log.warning("ensure_template_failed", template=name, exc=str(exc))
    log.info("ensure_templates_done", count=count)
    return count
