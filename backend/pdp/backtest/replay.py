"""On-demand full per-minute trace replay for a single (run, date).

Events-by-default keeps `backtest_decisions` bounded (task 3.2), but a user can ask for
the every-minute detail behind one day. Since the sim is deterministic for a fixed
config + window + data, replaying that single day off the run's pinned config
reproduces the same `BarStatus` trace + decision events without ever storing them.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Any

from pymongo import MongoClient

from pdp.backtest.commissions import CommissionCalculator
from pdp.backtest.day_loader import biz_days, load_window
from pdp.backtest.strangle_config import StrangleConfig, lot_size_for_date
from pdp.backtest.strangle_loader import build_strangle_day, load_pcr_window
from pdp.backtest.strangle_sim import format_status_line, simulate_strangle_day
from pdp.backtest.sweep_engine import load_vix_window
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar
from pdp.settings import get_settings

# Enough preceding trading days for EMA / weekly-Camarilla warmup context.
_WARMUP_DAYS = 40


def replay_day(config: dict[str, Any], underlying: str, target_date: str) -> dict[str, Any]:
    """Replay one (config, date) deterministically.

    Returns ``{"found": bool, "status_log": [str, ...], "decisions": [dict, ...]}``.
    """
    cfg = StrangleConfig.from_dict(config)
    td = date.fromisoformat(target_date)

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    cal_paths = {
        "NIFTY": s.EXPIRY_CACHE_PATH,
        "BANKNIFTY": s.BANKNIFTY_EXPIRY_CACHE_PATH,
        "SENSEX": s.SENSEX_EXPIRY_CACHE_PATH,
    }
    try:
        cal = NiftyExpiryCalendar.load(cal_paths.get(underlying, s.EXPIRY_CACHE_PATH))
    except Exception:
        cal = None

    days = [d for d in biz_days(td, _WARMUP_DAYS) if d <= td]
    if td not in days:
        days.append(td)
        days.sort()

    window = load_window(
        mdb, cal, days, security_id=cfg.security_id, underlying=underlying,
    )
    if td not in window.valid_days:
        return {"found": False, "status_log": [], "decisions": []}

    vix_sid = os.getenv("VIX_SECURITY_ID", "21")
    vix_by_day = load_vix_window(mdb, vix_sid, days)
    pcr_by_day = load_pcr_window(mdb["option_bars"], window.expiry_by_day, days, underlying=underlying)

    day_lot = lot_size_for_date(underlying, td)
    day_cfg = cfg if day_lot == cfg.lot_size else StrangleConfig.from_dict(
        {**cfg.to_dict(), "lot_size": day_lot})

    data = build_strangle_day(window, day_cfg, td, vix_by_day, pcr_by_day)
    if data is None:
        return {"found": False, "status_log": [], "decisions": []}

    calc = CommissionCalculator(s.backtest_commission)

    def commission_fn(side: str, turnover: float) -> float:
        return float(calc.calculate(side, Decimal(str(turnover))).total_inr)

    trace: list = []
    decisions: list[dict[str, Any]] = []
    simulate_strangle_day(day_cfg, data, commission_fn, trace=trace, decisions=decisions)

    return {
        "found": True,
        "status_log": [format_status_line(st) for st in trace],
        "decisions": [
            {**d, "ts_ist": d["ts_ist"].isoformat()} for d in decisions
        ],
    }
