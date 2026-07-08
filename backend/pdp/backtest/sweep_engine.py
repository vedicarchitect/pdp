"""In-process parameter-sweep engine for the directional-strangle backtest.

Loads the market window once per calendar-quarter chunk (spot + VIX + PCR — mirrors
``backtest/strangle_run.py``), then replays every grid combination through the same
``simulate_strangle_day`` engine. No subprocess, no duplicated simulation logic — this
is what ``pdp.backtest.job_handlers.backtest_sweep_handler`` calls in a worker thread.

Grid shape: ``{"<StrangleConfig field>": [v1, v2, ...], ...}``, e.g.
``{"hedge_enabled": [true, false], "day_loss_limit": [10000, 15000, 20000]}``.
Combos are the cartesian product of every field's value list, applied on top of
``base_config``. Ranking is fixed at ``(-profit_factor, -net)`` (mirrors
``backtest/run.py:print_table``) regardless of the requested ``objective`` label.
"""
from __future__ import annotations

import itertools
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from pymongo import MongoClient

from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator
from pdp.backtest.day_loader import load_window
from pdp.backtest.store import _sharpe_from_rets
from pdp.backtest.strangle_config import StrangleConfig, lot_size_for_date
from pdp.backtest.strangle_loader import build_strangle_day, load_pcr_window
from pdp.backtest.strangle_sim import simulate_strangle_day
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar
from pdp.settings import get_settings

_IST = timedelta(hours=5, minutes=30)


def load_vix_window(mdb: Any, vix_sid: str, days: list[date]) -> dict[date, list[dict]]:
    """Load 1m India VIX bars from market_bars, bucketed by IST trade-date."""
    out: dict[date, list[dict]] = {}
    if not days:
        return out
    lo = datetime(days[0].year, days[0].month, days[0].day, 0, 0, tzinfo=UTC)
    hi = datetime(days[-1].year, days[-1].month, days[-1].day, 23, 59, tzinfo=UTC)
    for b in mdb["market_bars"].find(
        {"metadata.security_id": vix_sid, "metadata.timeframe": "1m",
         "ts": {"$gte": lo, "$lte": hi}}).sort("ts", 1):
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        out.setdefault((ts + _IST).date(), []).append(b)
    return out


def _quarter_chunks(days: list[date]) -> list[list[date]]:
    chunks: dict[tuple[int, int], list[date]] = {}
    for d in days:
        chunks.setdefault((d.year, (d.month - 1) // 3), []).append(d)
    return [chunks[k] for k in sorted(chunks)]


def _parse_days(date_from: str, date_to: str) -> list[date]:
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def expand_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of a ``{field: [values]}`` grid -> list of override dicts."""
    if not grid:
        raise ValueError("sweep grid must have at least one field")
    keys = list(grid)
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]


def aggregate(results: list) -> dict[str, Any]:
    """Aggregate per-day DayResults into sweep-combo metrics (mirrors strangle_run.aggregate)."""
    gp = sum(r.realized for r in results if r.realized >= 0)
    gl = sum(r.realized for r in results if r.realized < 0)
    net = gp + gl
    pdays = sum(1 for r in results if r.realized >= 0)
    n = len(results)
    eq = peak = max_dd = 0.0
    for r in results:
        eq += r.realized
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    if gl < 0:
        profit_factor: float | None = gp / abs(gl)
    elif n > 0:
        profit_factor = None  # no losing days at all — treated as "best" (matches print_table's inf)
    else:
        profit_factor = 0.0  # no trading days in window — do not rank as best
    return {
        "days": n,
        "net": net,
        "gross_profit": gp,
        "gross_loss": gl,
        "profit_factor": profit_factor,
        "win_rate": (pdays / n * 100) if n else 0.0,
        "max_dd": max_dd,
        "sharpe": _sharpe_from_rets([r.realized for r in results]),
        "trades": sum(len(r.trades) for r in results),
        "halted": sum(1 for r in results if r.done_reason),
    }


def run_strangle_sweep(
    *,
    date_from: str,
    date_to: str,
    base_config: dict[str, Any],
    grid: dict[str, list[Any]],
    no_commission: bool = False,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Run every grid combo over the window (loaded once) and return unranked combos.

    Returns ``{"combos": [{"params": {...}, "metrics": {...}}], "window": {...}, "n_combos": int}``.
    Caller (job handler) builds + ranks the ``backtest_sweeps`` doc via
    ``pdp.backtest.store.build_sweep_doc``.
    """
    combos_overrides = expand_grid(grid)
    n_combos = len(combos_overrides)

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    base_cfg = StrangleConfig.from_dict(base_config or {})

    cal_paths = {
        "NIFTY": s.EXPIRY_CACHE_PATH,
        "BANKNIFTY": s.BANKNIFTY_EXPIRY_CACHE_PATH,
        "SENSEX": s.SENSEX_EXPIRY_CACHE_PATH,
    }
    try:
        cal = NiftyExpiryCalendar.load(cal_paths.get(base_cfg.underlying, s.EXPIRY_CACHE_PATH))
    except Exception:
        cal = None

    calc = NullCommissionCalculator(s.backtest_commission) if no_commission \
        else CommissionCalculator(s.backtest_commission)

    def commission_fn(side: str, turnover: float) -> float:
        return float(calc.calculate(side, Decimal(str(turnover))).total_inr)

    days = _parse_days(date_from, date_to)
    if not days:
        raise ValueError(f"No business days between {date_from} and {date_to}")
    chunks = _quarter_chunks(days)

    if on_progress:
        on_progress(5, f"loading {len(days)} biz days in {len(chunks)} chunk(s)")

    # Load every chunk's window/VIX/PCR ONCE — every combo below replays the same
    # cached inputs (only exits/sizing/hedge knobs vary per combo).
    loaded_chunks: list[tuple[Any, dict, dict]] = []
    vix_sid = os.getenv("VIX_SECURITY_ID", "21")
    for ci, chunk in enumerate(chunks, 1):
        window = load_window(
            mdb, cal, chunk, security_id=base_cfg.security_id,
            underlying=base_cfg.underlying,
        )
        vix_by_day = load_vix_window(mdb, vix_sid, chunk)
        pcr_by_day = load_pcr_window(mdb["option_bars"], window.expiry_by_day, chunk,
                                     underlying=base_cfg.underlying)
        loaded_chunks.append((window, vix_by_day, pcr_by_day))
        if on_progress:
            on_progress(5 + int(20 * ci / len(chunks)), f"loaded chunk {ci}/{len(chunks)}")

    combos: list[dict[str, Any]] = []
    for i, overrides in enumerate(combos_overrides, 1):
        cfg = StrangleConfig.from_dict({**base_cfg.to_dict(), **overrides})
        day_results = []
        for window, vix_by_day, pcr_by_day in loaded_chunks:
            for d in window.valid_days:
                day_lot = lot_size_for_date(cfg.underlying, d)
                day_cfg = cfg if day_lot == cfg.lot_size else StrangleConfig.from_dict(
                    {**cfg.to_dict(), "lot_size": day_lot})
                data = build_strangle_day(window, day_cfg, d, vix_by_day, pcr_by_day)
                if data is None:
                    continue
                r = simulate_strangle_day(day_cfg, data, commission_fn)
                if r is not None:
                    day_results.append(r)
        metrics = aggregate(day_results)
        combos.append({"params": overrides, "metrics": metrics})
        if on_progress:
            pf = metrics["profit_factor"]
            pf_s = f"{pf:.2f}" if pf is not None else "inf"
            pct = min(25 + int(70 * i / n_combos), 95)
            on_progress(pct, f"combo {i}/{n_combos} net={metrics['net']:+.0f} pf={pf_s}")

    return {
        "combos": combos,
        "window": {"from": date_from, "to": date_to, "biz_days": len(days)},
        "n_combos": n_combos,
    }
