"""backtest/sweep_all.py — Comprehensive parameter sweep across all experiment dimensions.

Loads the market window ONCE, then runs every experiment in EXPERIMENTS sequentially,
writing full per-trade detail (with DTE column) + per-day summary + ranked final table
to a timestamped log file under logs/.  Progress is printed to stdout.

Usage:
    python backtest/sweep_all.py --days 30 --no-heal
    python backtest/sweep_all.py --days 300 --no-heal
    task sweep:all -- --days 30 --no-heal
    task sweep:all -- --days 30 --section A,E      # run only sections A and E
    task sweep:all -- --days 30 --no-detail         # skip per-trade rows (summary only)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from pymongo import MongoClient  # noqa: E402

from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator  # noqa: E402
from pdp.backtest.day_loader import biz_days, build_day_data, load_window  # noqa: E402
from pdp.backtest.sim import simulate_day  # noqa: E402
from pdp.backtest.strategy_config import StrategyConfig  # noqa: E402
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar  # noqa: E402
from pdp.settings import get_settings  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# EXPERIMENTS — edit this block to add / remove / reorder runs.
#
# Each entry is either:
#   {"_section": "X", "_title": "..."} — section header (X = letter label A/B/C…)
#   ("label", overrides_dict)           — one experiment: _BASE merged with overrides
#
# _BASE = canonical ST(10,2)/15m/OTM1 (the promoted paper config).
# day_stop=12000 for 15m (in practice never triggers >10k; acts as black-swan cap).
# 5m experiments override day_stop=20000 explicitly since intraday swings are larger.
# ═══════════════════════════════════════════════════════════════════════════════

_BASE: dict = dict(
    st_period=10, st_multiplier=2.0,
    timeframe_min=15, moneyness=1,
    strike_step=50,
    base_lots=2, add_lots=1, max_lots=5, lot_size=65,
    start_ist="09:30", squareoff_ist="15:10",
    leg_stop_per_lot=3000.0, day_stop=12000.0,
    roll_enabled=True, roll_trigger_prem=20.0, roll_target_min_prem=50.0,
    scale_in_gate="premium_break", flip_mode="strangle",
)


def _e(label: str, **kw) -> tuple[str, dict]:
    return (label, {**_BASE, **kw})


EXPERIMENTS: list = [

    # ── A: Baseline grid ──────────────────────────────────────────────────────
    {"_section": "A", "_title": "BASELINE GRID  (TF × moneyness, canonical lots b2/a1/m5, ls=3000)"},
    _e("15m OTM3",  timeframe_min=15, moneyness=3),
    _e("15m OTM2",  timeframe_min=15, moneyness=2),
    _e("15m OTM1",  timeframe_min=15, moneyness=1),          # promoted paper config ★
    _e("15m ATM",   timeframe_min=15, moneyness=0),
    _e("5m OTM3",   timeframe_min=5,  moneyness=3, day_stop=20000.0),
    _e("5m OTM2",   timeframe_min=5,  moneyness=2, day_stop=20000.0),
    _e("5m OTM1",   timeframe_min=5,  moneyness=1, day_stop=20000.0),
    _e("5m ATM",    timeframe_min=5,  moneyness=0, day_stop=20000.0),

    # ── B: 15m lot sizing ─────────────────────────────────────────────────────
    {"_section": "B", "_title": "15m LOT SIZING  (OTM1 + OTM2, ls=3000, ds=12000)"},
    # — OTM1 —
    _e("15m OTM1 b1a0m1", timeframe_min=15, moneyness=1, base_lots=1, add_lots=0, max_lots=1),
    _e("15m OTM1 b1a1m3", timeframe_min=15, moneyness=1, base_lots=1, add_lots=1, max_lots=3),
    _e("15m OTM1 b2a1m5", timeframe_min=15, moneyness=1, base_lots=2, add_lots=1, max_lots=5),  # ★
    _e("15m OTM1 b3a1m5", timeframe_min=15, moneyness=1, base_lots=3, add_lots=1, max_lots=5),
    _e("15m OTM1 b3a1m7", timeframe_min=15, moneyness=1, base_lots=3, add_lots=1, max_lots=7),
    _e("15m OTM1 b2a2m6", timeframe_min=15, moneyness=1, base_lots=2, add_lots=2, max_lots=6),
    _e("15m OTM1 b3a2m7", timeframe_min=15, moneyness=1, base_lots=3, add_lots=2, max_lots=7),
    # — OTM2 —
    _e("15m OTM2 b1a0m1", timeframe_min=15, moneyness=2, base_lots=1, add_lots=0, max_lots=1),
    _e("15m OTM2 b1a1m3", timeframe_min=15, moneyness=2, base_lots=1, add_lots=1, max_lots=3),
    _e("15m OTM2 b2a1m5", timeframe_min=15, moneyness=2, base_lots=2, add_lots=1, max_lots=5),  # ★
    _e("15m OTM2 b3a1m5", timeframe_min=15, moneyness=2, base_lots=3, add_lots=1, max_lots=5),
    _e("15m OTM2 b3a1m7", timeframe_min=15, moneyness=2, base_lots=3, add_lots=1, max_lots=7),
    _e("15m OTM2 b2a2m6", timeframe_min=15, moneyness=2, base_lots=2, add_lots=2, max_lots=6),
    _e("15m OTM2 b3a2m7", timeframe_min=15, moneyness=2, base_lots=3, add_lots=2, max_lots=7),

    # ── C: 15m leg-stop sweep ─────────────────────────────────────────────────
    {"_section": "C", "_title": "15m LEG STOP SWEEP  (OTM1 + OTM2, b2a1m5, ds=12000)"},
    _e("15m OTM1 ls1000",  timeframe_min=15, moneyness=1, leg_stop_per_lot=1000.0),
    _e("15m OTM1 ls1500",  timeframe_min=15, moneyness=1, leg_stop_per_lot=1500.0),
    _e("15m OTM1 ls2000",  timeframe_min=15, moneyness=1, leg_stop_per_lot=2000.0),
    _e("15m OTM1 ls3000",  timeframe_min=15, moneyness=1, leg_stop_per_lot=3000.0),  # ★
    _e("15m OTM1 ls4000",  timeframe_min=15, moneyness=1, leg_stop_per_lot=4000.0),
    _e("15m OTM1 ls5000",  timeframe_min=15, moneyness=1, leg_stop_per_lot=5000.0),
    _e("15m OTM2 ls1000",  timeframe_min=15, moneyness=2, leg_stop_per_lot=1000.0),
    _e("15m OTM2 ls1500",  timeframe_min=15, moneyness=2, leg_stop_per_lot=1500.0),
    _e("15m OTM2 ls2000",  timeframe_min=15, moneyness=2, leg_stop_per_lot=2000.0),
    _e("15m OTM2 ls3000",  timeframe_min=15, moneyness=2, leg_stop_per_lot=3000.0),  # ★
    _e("15m OTM2 ls4000",  timeframe_min=15, moneyness=2, leg_stop_per_lot=4000.0),
    _e("15m OTM2 ls5000",  timeframe_min=15, moneyness=2, leg_stop_per_lot=5000.0),

    # ── D: 15m day-stop sweep ─────────────────────────────────────────────────
    {"_section": "D", "_title": "15m DAY STOP SWEEP  (OTM1 + OTM2, b2a1m5, ls=3000)"},
    _e("15m OTM1 ds8000",   timeframe_min=15, moneyness=1, day_stop=8000.0),
    _e("15m OTM1 ds10000",  timeframe_min=15, moneyness=1, day_stop=10000.0),
    _e("15m OTM1 ds12000",  timeframe_min=15, moneyness=1, day_stop=12000.0),  # ★
    _e("15m OTM1 ds15000",  timeframe_min=15, moneyness=1, day_stop=15000.0),
    _e("15m OTM1 ds20000",  timeframe_min=15, moneyness=1, day_stop=20000.0),
    _e("15m OTM2 ds8000",   timeframe_min=15, moneyness=2, day_stop=8000.0),
    _e("15m OTM2 ds10000",  timeframe_min=15, moneyness=2, day_stop=10000.0),
    _e("15m OTM2 ds12000",  timeframe_min=15, moneyness=2, day_stop=12000.0),  # ★
    _e("15m OTM2 ds15000",  timeframe_min=15, moneyness=2, day_stop=15000.0),
    _e("15m OTM2 ds20000",  timeframe_min=15, moneyness=2, day_stop=20000.0),

    # ── E: 5m lot sizing ──────────────────────────────────────────────────────
    {"_section": "E", "_title": "5m LOT SIZING  (OTM1 + OTM2, ls=3000, ds=20000)"},
    # — OTM1 —
    _e("5m OTM1 b1a0m1", timeframe_min=5, moneyness=1, base_lots=1, add_lots=0, max_lots=1, day_stop=20000.0),
    _e("5m OTM1 b1a1m3", timeframe_min=5, moneyness=1, base_lots=1, add_lots=1, max_lots=3, day_stop=20000.0),
    _e("5m OTM1 b2a1m5", timeframe_min=5, moneyness=1, base_lots=2, add_lots=1, max_lots=5, day_stop=20000.0),  # ★
    _e("5m OTM1 b3a1m5", timeframe_min=5, moneyness=1, base_lots=3, add_lots=1, max_lots=5, day_stop=20000.0),
    _e("5m OTM1 b3a1m7", timeframe_min=5, moneyness=1, base_lots=3, add_lots=1, max_lots=7, day_stop=20000.0),
    _e("5m OTM1 b2a2m6", timeframe_min=5, moneyness=1, base_lots=2, add_lots=2, max_lots=6, day_stop=20000.0),
    _e("5m OTM1 b3a2m7", timeframe_min=5, moneyness=1, base_lots=3, add_lots=2, max_lots=7, day_stop=20000.0),
    # — OTM2 —
    _e("5m OTM2 b1a0m1", timeframe_min=5, moneyness=2, base_lots=1, add_lots=0, max_lots=1, day_stop=20000.0),
    _e("5m OTM2 b1a1m3", timeframe_min=5, moneyness=2, base_lots=1, add_lots=1, max_lots=3, day_stop=20000.0),
    _e("5m OTM2 b2a1m5", timeframe_min=5, moneyness=2, base_lots=2, add_lots=1, max_lots=5, day_stop=20000.0),  # ★
    _e("5m OTM2 b3a1m5", timeframe_min=5, moneyness=2, base_lots=3, add_lots=1, max_lots=5, day_stop=20000.0),
    _e("5m OTM2 b3a1m7", timeframe_min=5, moneyness=2, base_lots=3, add_lots=1, max_lots=7, day_stop=20000.0),
    _e("5m OTM2 b2a2m6", timeframe_min=5, moneyness=2, base_lots=2, add_lots=2, max_lots=6, day_stop=20000.0),
    _e("5m OTM2 b3a2m7", timeframe_min=5, moneyness=2, base_lots=3, add_lots=2, max_lots=7, day_stop=20000.0),

    # ── F: 5m leg-stop sweep ──────────────────────────────────────────────────
    {"_section": "F", "_title": "5m LEG STOP SWEEP  (OTM1 + OTM2, b2a1m5, ds=20000)"},
    _e("5m OTM1 ls1000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=1000.0, day_stop=20000.0),
    _e("5m OTM1 ls1500",  timeframe_min=5, moneyness=1, leg_stop_per_lot=1500.0, day_stop=20000.0),
    _e("5m OTM1 ls2000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=2000.0, day_stop=20000.0),
    _e("5m OTM1 ls3000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=3000.0, day_stop=20000.0),  # ★
    _e("5m OTM1 ls4000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=4000.0, day_stop=20000.0),
    _e("5m OTM2 ls1000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=1000.0, day_stop=20000.0),
    _e("5m OTM2 ls1500",  timeframe_min=5, moneyness=2, leg_stop_per_lot=1500.0, day_stop=20000.0),
    _e("5m OTM2 ls2000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=2000.0, day_stop=20000.0),
    _e("5m OTM2 ls3000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=3000.0, day_stop=20000.0),  # ★
    _e("5m OTM2 ls4000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=4000.0, day_stop=20000.0),

    # ── G: 5m day-stop sweep (uses ls=2000 as the known-good 5m leg-stop) ────
    {"_section": "G", "_title": "5m DAY STOP SWEEP  (OTM1 + OTM2, b2a1m5, ls=2000)"},
    _e("5m OTM1 ds10000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=2000.0, day_stop=10000.0),
    _e("5m OTM1 ds15000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=2000.0, day_stop=15000.0),
    _e("5m OTM1 ds20000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=2000.0, day_stop=20000.0),  # ★
    _e("5m OTM1 ds25000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=2000.0, day_stop=25000.0),
    _e("5m OTM1 ds30000",  timeframe_min=5, moneyness=1, leg_stop_per_lot=2000.0, day_stop=30000.0),
    _e("5m OTM2 ds10000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=2000.0, day_stop=10000.0),
    _e("5m OTM2 ds15000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=2000.0, day_stop=15000.0),
    _e("5m OTM2 ds20000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=2000.0, day_stop=20000.0),  # ★
    _e("5m OTM2 ds25000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=2000.0, day_stop=25000.0),
    _e("5m OTM2 ds30000",  timeframe_min=5, moneyness=2, leg_stop_per_lot=2000.0, day_stop=30000.0),

    # ── H: 5m + 15m OTM1 combined best-of (ls+ds tuned together) ─────────────
    {"_section": "H", "_title": "COMBINED BEST-OF  (tuned ls+ds combos for 5m and 15m)"},
    _e("15m OTM1 ls2000 ds12k", timeframe_min=15, moneyness=1, leg_stop_per_lot=2000.0, day_stop=12000.0),
    _e("15m OTM1 ls1500 ds12k", timeframe_min=15, moneyness=1, leg_stop_per_lot=1500.0, day_stop=12000.0),
    _e("15m OTM2 ls2000 ds12k", timeframe_min=15, moneyness=2, leg_stop_per_lot=2000.0, day_stop=12000.0),
    _e("15m OTM2 ls1500 ds12k", timeframe_min=15, moneyness=2, leg_stop_per_lot=1500.0, day_stop=12000.0),
    _e("15m OTM1 b3a1m7 ls2k",  timeframe_min=15, moneyness=1, base_lots=3, add_lots=1, max_lots=7, leg_stop_per_lot=2000.0),
    _e("15m OTM2 b3a1m7 ls2k",  timeframe_min=15, moneyness=2, base_lots=3, add_lots=1, max_lots=7, leg_stop_per_lot=2000.0),
    _e("5m OTM1 ls2k ds20k",    timeframe_min=5, moneyness=1, leg_stop_per_lot=2000.0, day_stop=20000.0),
    _e("5m OTM1 ls2k ds25k",    timeframe_min=5, moneyness=1, leg_stop_per_lot=2000.0, day_stop=25000.0),
    _e("5m OTM2 ls2k ds20k",    timeframe_min=5, moneyness=2, leg_stop_per_lot=2000.0, day_stop=20000.0),
    _e("5m OTM1 b3a1m7 ls2k ds20k", timeframe_min=5, moneyness=1, base_lots=3, add_lots=1, max_lots=7, leg_stop_per_lot=2000.0, day_stop=20000.0),
    _e("5m OTM2 b3a1m7 ls2k ds20k", timeframe_min=5, moneyness=2, base_lots=3, add_lots=1, max_lots=7, leg_stop_per_lot=2000.0, day_stop=20000.0),

    # ── I: 5m EMA early exit (baseline = 5m OTM2 b3a1m7 ls2k ds20k, rank #11) ──
    {"_section": "I", "_title": "5m EMA EARLY EXIT  (baseline 5m OTM2 b3a1m7 ls2k ds20k, PF 1.34 — target ≥ 1.45)"},
    # 9-EMA: exit after 2 consecutive bars with NIFTY close on the wrong side
    _e("5m OTM2 b3m7 ema9-2bar",   timeframe_min=5, moneyness=2, base_lots=3, add_lots=1, max_lots=7,
       leg_stop_per_lot=2000.0, day_stop=20000.0,
       early_exit_ema_fast=9, early_exit_ema_confirm_bars=2,
       suite_indicators=[{"family": "ema", "periods": [9, 20]}]),
    # 20-EMA: instant exit on first close breach
    _e("5m OTM2 b3m7 ema20-instant", timeframe_min=5, moneyness=2, base_lots=3, add_lots=1, max_lots=7,
       leg_stop_per_lot=2000.0, day_stop=20000.0,
       early_exit_ema_slow=20,
       suite_indicators=[{"family": "ema", "periods": [20]}]),
    # Combined: 9-EMA 2-bar OR 20-EMA instant (whichever fires first)
    _e("5m OTM2 b3m7 ema9or20",    timeframe_min=5, moneyness=2, base_lots=3, add_lots=1, max_lots=7,
       leg_stop_per_lot=2000.0, day_stop=20000.0,
       early_exit_ema_fast=9, early_exit_ema_slow=20, early_exit_ema_confirm_bars=2,
       suite_indicators=[{"family": "ema", "periods": [9, 20]}]),
    # OTM1 baseline with 9-EMA 2-bar (compare to OTM2 to see if moneyness matters for EMA exit)
    _e("5m OTM1 b2m5 ema9-2bar",   timeframe_min=5, moneyness=1, day_stop=20000.0,
       early_exit_ema_fast=9, early_exit_ema_confirm_bars=2,
       suite_indicators=[{"family": "ema", "periods": [9, 20]}]),
]

# ═══════════════════════════════════════════════════════════════════════════════

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_W = 140  # log line width


# ── helpers ───────────────────────────────────────────────────────────────────

def _dte(trade_date_str: str, expiry_str: str) -> int:
    """Calendar days from trade date to actual expiry date."""
    return (date.fromisoformat(expiry_str) - date.fromisoformat(trade_date_str)).days


def _dow(trade_date_str: str) -> str:
    return _DOW[date.fromisoformat(trade_date_str).weekday()]


def _last_biz_day(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# ── dual output (log file + stdout) ──────────────────────────────────────────

class Output:
    def __init__(self, log_path: Path) -> None:
        self._f = log_path.open("w", buffering=1, encoding="utf-8")

    def log(self, msg: str = "") -> None:
        """Write to log file only (detail that would flood stdout)."""
        self._f.write(msg + "\n")

    def both(self, msg: str = "") -> None:
        """Write to stdout AND log file."""
        print(msg)
        self._f.write(msg + "\n")

    def close(self) -> None:
        self._f.close()


# ── metrics ───────────────────────────────────────────────────────────────────

def aggregate(results: list) -> dict:
    gp = sum(r.realized for r in results if r.realized >= 0)
    gl = sum(r.realized for r in results if r.realized < 0)
    net = gp + gl
    pdays = sum(1 for r in results if r.realized >= 0)
    n = len(results)
    trades = sum(len(r.trades) for r in results)
    stopped = sum(1 for r in results if r.done_reason)
    eq = peak = max_dd = 0.0
    for r in results:
        eq += r.realized
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    return dict(
        days=n, net=net, gross_profit=gp, gross_loss=gl,
        profit_factor=(gp / abs(gl)) if gl else float("inf"),
        win_rate=(pdays / n * 100) if n else 0.0,
        max_dd=max_dd, trades=trades, stopped=stopped,
    )


# ── per-day log writers ───────────────────────────────────────────────────────

def _write_day(out: Output, r, show_trades: bool) -> None:
    dte = _dte(r.date, r.expiry)
    dow = _dow(r.date)
    stop_s = f"  [STOP: {r.done_reason}]" if r.done_reason else ""
    out.log(f"\n  {'─'*(_W-4)}")
    out.log(
        f"  {r.date} ({dow})  DTE={dte}  |  "
        f"NIFTY {r.nifty_open:.2f} → {r.nifty_close:.2f} ({r.nifty_chg:+.2f})  |  "
        f"Expiry: {r.expiry}  |  Bars: {r.nifty_bars}{stop_s}"
    )

    if not r.trades:
        out.log("  (no trades this day)")
        return

    if show_trades:
        out.log(
            f"  {'#':>3}  {'Side':<4}  {'T':<2} {'Strike':>7}  {'Time':>5}  "
            f"{'Qty':>5}  {'Price':>7}  {'NIFTY':>9}  "
            f"{'CumL':>5}  {'AvgE':>8}  {'LegPNL':>9}  {'DayPNL':>10}  Note"
        )
        out.log(
            f"  {'-'*3}  {'-'*4}  {'-'*2} {'-'*7}  {'-'*5}  "
            f"{'-'*5}  {'-'*7}  {'-'*9}  "
            f"{'-'*5}  {'-'*8}  {'-'*9}  {'-'*10}  ----"
        )
        for i, t in enumerate(r.trades, 1):
            leg_s = f"{t.leg_pnl:>+9.2f}" if t.leg_pnl is not None else f"{'':>9}"
            out.log(
                f"  {i:>3}  {t.side:<4}  {t.opt_type:<2} {t.strike:>7.0f}  "
                f"{t.bar_time.strftime('%H:%M'):>5}  "
                f"{t.qty:>5}  {t.price:>7.2f}  {t.nifty:>9.2f}  "
                f"{t.cum_lots:>5}L  {t.avg_entry:>8.2f}  {leg_s}  {t.day_pnl:>+10.2f}  {t.note}"
            )
        out.log(f"  {'-'*(_W-4)}")

    out.log(
        f"  Gross: {r.gross_pnl:>+10.2f}   Charges: -{r.commission:.2f}   "
        f"Realized: {r.realized:>+10.2f}"
    )

    if r.leg_records:
        wins = sum(1 for lr in r.leg_records if lr.leg_pnl >= 0)
        total_leg = sum(lr.leg_pnl for lr in r.leg_records)
        out.log()
        out.log(
            f"  {'#':>3}  {'T':<2} {'Strike':>7}  {'Entry':>5}  {'Exit':>5}  "
            f"{'Lots':>4}  {'AvgE':>8}  {'ExitPx':>7}  {'LegPNL':>10}  Reason"
        )
        out.log(
            f"  {'-'*3}  {'-'*2} {'-'*7}  {'-'*5}  {'-'*5}  "
            f"{'-'*4}  {'-'*8}  {'-'*7}  {'-'*10}  ------"
        )
        for i, lr in enumerate(r.leg_records, 1):
            out.log(
                f"  {i:>3}  {lr.opt_type:<2} {lr.strike:>7.0f}  "
                f"{lr.entry_ist.strftime('%H:%M'):>5}  "
                f"{lr.exit_ist.strftime('%H:%M'):>5}  "
                f"{lr.lots:>4}L  {lr.avg_entry:>8.2f}  {lr.exit_px:>7.2f}  "
                f"{lr.leg_pnl:>+10.2f}  {lr.reason}"
            )
        out.log(
            f"  legs={len(r.leg_records)}  Win={wins}  Loss={len(r.leg_records)-wins}  "
            f"Total: {total_leg:+.2f}"
        )


def _write_exp_summary(out: Output, m: dict, results: list) -> None:
    """Per-day summary table for one experiment + DTE distribution."""
    out.log()
    out.log(
        f"  {'Date':<12}  {'DOW':<3}  {'DTE':>3}  {'NIFTY Chg':>10}  "
        f"{'Trades':>6}  {'Gross':>11}  {'Charges':>8}  {'Net':>11}  Status"
    )
    out.log(
        f"  {'-'*12}  {'-'*3}  {'-'*3}  {'-'*10}  "
        f"{'-'*6}  {'-'*11}  {'-'*8}  {'-'*11}  ------"
    )
    dte_counts: dict[int, dict] = {}
    for r in results:
        dte = _dte(r.date, r.expiry)
        dow = _dow(r.date)
        stat = "P" if r.realized >= 0 else "L"
        stp = " STOP" if r.done_reason else ""
        out.log(
            f"  {r.date:<12}  {dow:<3}  {dte:>3}  {r.nifty_chg:>+10.2f}  "
            f"{len(r.trades):>6}  {r.gross_pnl:>+11.2f}  {r.commission:>8.2f}  "
            f"{r.realized:>+11.2f}  [{stat}]{stp}"
        )
        if dte not in dte_counts:
            dte_counts[dte] = {"days": 0, "net": 0.0, "trades": 0, "wins": 0}
        dte_counts[dte]["days"] += 1
        dte_counts[dte]["net"] += r.realized
        dte_counts[dte]["trades"] += len(r.trades)
        if r.realized >= 0:
            dte_counts[dte]["wins"] += 1

    out.log(f"  {'-'*90}")
    pf_s = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    out.log(
        f"  Net {m['net']:>+.0f}  |  PF {pf_s}  |  Win {m['win_rate']:.0f}%  |  "
        f"MaxDD {m['max_dd']:.0f}  |  Trades {m['trades']}  |  Stops {m['stopped']}"
    )

    # DTE distribution
    if dte_counts:
        out.log()
        out.log("  DTE DISTRIBUTION:")
        out.log(
            f"  {'DTE':>4}  {'Days':>5}  {'Wins':>5}  {'Win%':>5}  "
            f"{'Trades':>7}  {'Net':>12}  {'Avg/Day':>10}"
        )
        out.log(f"  {'-'*4}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*7}  {'-'*12}  {'-'*10}")
        for dte in sorted(dte_counts):
            d = dte_counts[dte]
            win_pct = d["wins"] / d["days"] * 100 if d["days"] else 0.0
            avg = d["net"] / d["days"] if d["days"] else 0.0
            out.log(
                f"  {dte:>4}  {d['days']:>5}  {d['wins']:>5}  {win_pct:>5.0f}  "
                f"{d['trades']:>7}  {d['net']:>+12.0f}  {avg:>+10.0f}"
            )


# ── final ranked table ────────────────────────────────────────────────────────

def _write_final_table(out: Output, rows: list[dict], n_days: int) -> None:
    rows = sorted(
        rows,
        key=lambda r: (-(r["profit_factor"] if r["profit_factor"] != float("inf") else 1e9), -r["net"]),
    )
    out.both(f"\n{'='*130}")
    out.both(
        f"  FINAL RANKED SUMMARY  ({n_days} traded days, {len(rows)} experiments)"
        f"  — sorted by PF ↓ then Net ↓"
    )
    out.both(f"{'='*130}")
    out.both(
        f"  {'#':>3}  {'Sec':>3}  {'Label':<32}  {'Net':>12}  {'PF':>6}  {'Win%':>5}  "
        f"{'MaxDD':>10}  {'Trades':>6}  {'Stops':>5}  {'GrossP':>11}  {'GrossL':>11}"
    )
    out.both(
        f"  {'-'*3}  {'-'*3}  {'-'*32}  {'-'*12}  {'-'*6}  {'-'*5}  "
        f"{'-'*10}  {'-'*6}  {'-'*5}  {'-'*11}  {'-'*11}"
    )
    for i, r in enumerate(rows, 1):
        pf_s = "inf" if r["profit_factor"] == float("inf") else f"{r['profit_factor']:.2f}"
        out.both(
            f"  {i:>3}  {r['section']:>3}  {r['label']:<32}  {r['net']:>+12.0f}  {pf_s:>6}  "
            f"{r['win_rate']:>5.0f}  {r['max_dd']:>10.0f}  {r['trades']:>6}  "
            f"{r['stopped']:>5}  {r['gross_profit']:>+11.0f}  {r['gross_loss']:>+11.0f}"
        )
    out.both(f"{'='*130}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--days", type=int, default=30, help="Trading-day window (default 30)")
    ap.add_argument("--start", type=str, default=None, help="End date YYYY-MM-DD (default: last biz day)")
    ap.add_argument("--no-heal", action="store_true", help="Skip auto-heal gap fill")
    ap.add_argument("--no-commission", action="store_true", help="Zero commissions")
    ap.add_argument("--no-detail", action="store_true", help="Skip per-trade rows in log (summary-only)")
    ap.add_argument(
        "--section", type=str, default=None,
        metavar="A,B,C", help="Run only specific section letters (comma-separated)"
    )
    args = ap.parse_args()

    sections_filter: set[str] | None = (
        set(s.strip().upper() for s in args.section.split(",")) if args.section else None
    )

    # ── connections ───────────────────────────────────────────────────────────
    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    try:
        cal = NiftyExpiryCalendar.load(s.EXPIRY_CACHE_PATH)
    except Exception:
        cal = None

    calc = (
        NullCommissionCalculator(s.backtest_commission) if args.no_commission
        else CommissionCalculator(s.backtest_commission)
    )

    def commission_fn(side: str, turnover: float) -> float:
        return float(calc.calculate(side, Decimal(str(turnover))).total_inr)

    end = date.fromisoformat(args.start) if args.start else _last_biz_day(date.today())
    days = biz_days(end, args.days)

    # ── auto-heal ─────────────────────────────────────────────────────────────
    if not args.no_heal and cal is not None and s.DHAN_CLIENT_ID and s.DHAN_ACCESS_TOKEN:
        try:
            from dhanhq import DhanContext, dhanhq  # noqa: PLC0415
            dhan = dhanhq(DhanContext(s.DHAN_CLIENT_ID, s.DHAN_ACCESS_TOKEN))
            from pdp.options.gap_backfill import backfill_gaps  # noqa: PLC0415
            backfill_gaps(
                dhan=dhan, col=mdb["option_bars"], cal=cal, days=days,
                ladder=[("WEEK", 1), ("WEEK", 2)], band=s.WAREHOUSE_STRIKE_BAND, only_missing=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [auto-heal] skipped: {exc}")

    # ── load window (once for all experiments) ────────────────────────────────
    print(f"Loading window: {args.days} biz days ending {end}...")
    window = load_window(mdb, cal, days)
    n_valid = len(window.valid_days)
    n_skip = len(window.skipped)
    print(f"Window: {n_valid} valid days, {n_skip} skipped\n")

    if not n_valid:
        print("No valid trading days in window (check data).")
        return 1

    # ── log file ──────────────────────────────────────────────────────────────
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"sweep_{ts}.log"
    out = Output(log_path)

    started_at = datetime.now()
    out.both(f"PDP Backtest Sweep  —  {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    out.both(f"Window : {args.days} biz days → {n_valid} traded days, {n_skip} skipped")
    out.both(f"Log    : {log_path}")
    if sections_filter:
        out.both(f"Sections filter: {sorted(sections_filter)}")
    out.both()

    # ── count active experiments ──────────────────────────────────────────────
    cur_sec: str | None = None
    total_exps = 0
    for item in EXPERIMENTS:
        if isinstance(item, dict):
            cur_sec = item["_section"]
        elif isinstance(item, tuple):
            if sections_filter is None or cur_sec in sections_filter:
                total_exps += 1

    print(f"Experiments to run: {total_exps}")
    out.log(f"Experiments to run: {total_exps}")
    out.log()

    # ── run loop ──────────────────────────────────────────────────────────────
    active_section: str | None = None
    all_rows: list[dict] = []
    exp_num = 0

    for item in EXPERIMENTS:
        if isinstance(item, dict):
            active_section = item["_section"]
            if sections_filter and active_section not in sections_filter:
                continue
            out.both(f"\n{'#'*_W}")
            out.both(f"  SECTION {active_section}: {item['_title']}")
            out.both(f"{'#'*_W}")
            continue

        if sections_filter and active_section not in sections_filter:
            continue

        label, cfg_dict = item
        exp_num += 1
        cfg = StrategyConfig.from_dict(cfg_dict)

        print(f"  [{exp_num:>3}/{total_exps}] {label:<40}", end="", flush=True)

        out.log(f"\n{'═'*_W}")
        out.log(
            f"  EXP {exp_num}/{total_exps} [{active_section}]: {label}"
        )
        out.log(
            f"  tf={cfg.timeframe_min}m  mny={cfg.moneyness}  "
            f"lots=b{cfg.base_lots}/a{cfg.add_lots}/m{cfg.max_lots}  "
            f"ls={cfg.leg_stop_per_lot:.0f}  ds={cfg.day_stop:.0f}  "
            f"st=({cfg.st_period},{cfg.st_multiplier})"
        )
        out.log(f"{'═'*_W}")

        # Run
        results = []
        for d in window.valid_days:
            r = simulate_day(cfg, build_day_data(window, cfg, d), commission_fn)
            if r is not None:
                results.append(r)

        m = aggregate(results)

        # Write per-day detail to log
        for r in results:
            _write_day(out, r, show_trades=not args.no_detail)

        # Write per-day summary + DTE distribution to log
        out.log()
        _write_exp_summary(out, m, results)

        # stdout progress line
        pf_s = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(
            f"  Net {m['net']:>+10,.0f}  PF {pf_s:>5}  "
            f"Win {m['win_rate']:>3.0f}%  Trades {m['trades']:>4}  Stops {m['stopped']}"
        )

        all_rows.append(dict(**m, label=label, section=active_section or "?"))

    # ── final summary ─────────────────────────────────────────────────────────
    _write_final_table(out, all_rows, n_valid)

    elapsed = (datetime.now() - started_at).total_seconds()
    out.both(f"\nCompleted {exp_num} experiments in {elapsed:.0f}s")
    out.both(f"Log: {log_path}")
    out.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
