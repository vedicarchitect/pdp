"""Backtest vs paper comparison for SuperTrend option-selling strategy.

Replays the SuperTrend strategy on historical MongoDB bars for a given IST date
and prints a side-by-side comparison against that day's paper journal stats.
Does NOT write to any PostgreSQL table.

Usage:
    python backtest/compare.py [--date YYYY-MM-DD]

Defaults to today's IST date when --date is omitted.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
from datetime import timezone as _UTC
import os
import sys
from decimal import Decimal
from zoneinfo import ZoneInfo

import asyncpg
from dotenv import load_dotenv
from pymongo import MongoClient

# Allow running from repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from pdp.indicators.supertrend import SuperTrendTracker  # noqa: E402

load_dotenv()

_IST = ZoneInfo("Asia/Kolkata")
_MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
_MONGO_DB = os.getenv("MONGO_DB_NAME", "pdp")
_DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")

# ---- Strategy params (mirrors strategies/supertrend_short.yaml) ----
LOT_SIZE = 65
START_LOTS = 2
ADD_LOTS = 1
MAX_LOTS = 5
START_IST = datetime.time(9, 30)
SQUAREOFF_IST = datetime.time(15, 10)
LEG_STOP_PER_LOT = Decimal("1000")
DAY_STOP = Decimal("10000")
STRIKE_STEP = 50
OTM_STEPS = 1
NIFTY_SID = "13"
TIMEFRAME = "5m"
ST_PERIOD = 3
ST_MULTIPLIER = 1


# ---- helpers ----

def _as_ist(ts: datetime.datetime) -> datetime.datetime:
    """Convert a naive-UTC PyMongo timestamp to an IST-aware datetime."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_UTC.utc)
    return ts.astimezone(_IST)


def _utc_window(date_ist: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    """Return UTC start/end covering the full IST trading day."""
    start = datetime.datetime(date_ist.year, date_ist.month, date_ist.day, 3, 30)
    end = datetime.datetime(date_ist.year, date_ist.month, date_ist.day, 10, 5)
    return start, end


def _prior_utc_window(date_ist: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    """Return UTC window for the previous calendar day's last few 5m bars."""
    prev = date_ist - datetime.timedelta(days=1)
    start = datetime.datetime(prev.year, prev.month, prev.day, 3, 30)
    end = datetime.datetime(prev.year, prev.month, prev.day, 10, 5)
    return start, end


def _load_bars(
    db,
    security_id: str,
    timeframe: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[dict]:
    return list(
        db["market_bars"]
        .find(
            {
                "metadata.security_id": security_id,
                "metadata.timeframe": timeframe,
                "ts": {"$gte": start, "$lte": end},
            },
            {"_id": 0},
        )
        .sort("ts", 1)
    )


def _opt_price_index(db, sids: list[str], start: datetime.datetime, end: datetime.datetime) -> dict:
    """Return {security_id: {ts: close}} for all listed sids."""
    idx: dict[str, dict] = {}
    for b in db["market_bars"].find(
        {
            "metadata.security_id": {"$in": sids},
            "metadata.timeframe": TIMEFRAME,
            "ts": {"$gte": start, "$lte": end},
        },
        {"_id": 0},
    ):
        sid = b["metadata"]["security_id"]
        idx.setdefault(sid, {})[b["ts"]] = Decimal(str(b["close"]))
    return idx


async def _load_instruments(sids: list[str]) -> dict[str, dict]:
    conn = await asyncpg.connect(_DB_URL)
    try:
        rows = await conn.fetch(
            "SELECT security_id, trading_symbol, option_type, strike "
            "FROM instruments WHERE security_id = ANY($1::text[])",
            sids,
        )
        return {r["security_id"]: dict(r) for r in rows}
    finally:
        await conn.close()


async def _load_nifty_option_instruments(strikes: list[float], option_type: str) -> list[dict]:
    """Return instrument rows for NIFTY options at given strikes."""
    conn = await asyncpg.connect(_DB_URL)
    try:
        rows = await conn.fetch(
            "SELECT security_id, trading_symbol, option_type, strike "
            "FROM instruments "
            "WHERE name = 'NIFTY' AND option_type = $1 "
            "  AND strike = ANY($2::numeric[]) "
            "ORDER BY expiry ASC",
            option_type,
            strikes,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def _get_ltp(opt_idx: dict, sid: str, ts: datetime.datetime) -> Decimal | None:
    """Return the most recent non-zero option close at or before ts.

    Bar-close is used as fill price proxy. Bars with close=0 (no ticks that period)
    are skipped; the last non-zero close up to and including ts is used instead.
    """
    prices = opt_idx.get(sid, {})
    candidates = [p for t, p in sorted(prices.items()) if t <= ts and p > 0]
    return candidates[-1] if candidates else None


def _resolve_option(instruments: dict[str, dict], option_type: str, spot: Decimal) -> str | None:
    """Pick the security_id for the OTM-1 option given spot and option_type."""
    atm = round(float(spot) / STRIKE_STEP) * STRIKE_STEP
    otm_strike = atm - STRIKE_STEP * OTM_STEPS if option_type == "PE" else atm + STRIKE_STEP * OTM_STEPS
    # exact match first
    for sid, inst in instruments.items():
        if inst["option_type"] == option_type and abs(float(inst["strike"]) - otm_strike) < 0.01:
            return sid
    # nearest match fallback
    matches = [(sid, inst) for sid, inst in instruments.items() if inst["option_type"] == option_type]
    if not matches:
        return None
    return min(matches, key=lambda x: abs(float(x[1]["strike"]) - otm_strike))[0]


# ---- simulation ----

def simulate(
    nifty_bars: list[dict],
    opt_idx: dict,
    instruments: dict[str, dict],
    seed_bars: list[dict] | None = None,
) -> tuple[list[dict], Decimal]:
    """
    Replay SuperTrend strategy on nifty_bars.
    seed_bars (prior-session bars) are fed through the tracker first to warm it up
    without triggering any trading logic.
    Returns (trades, day_realized_pnl).
    Each trade: entry_ts, exit_ts, sid, sym, lots, entry_px, exit_px, pnl, reason.
    """
    tracker = SuperTrendTracker(period=ST_PERIOD, multiplier=ST_MULTIPLIER)
    # Warm up tracker with prior-session bars — no trading, just ATR seeding
    for bar in (seed_bars or []):
        tracker.update(bar["high"], bar["low"], bar["close"], bar["ts"])
    trades: list[dict] = []
    current: dict | None = None
    done = False
    day_pnl = Decimal("0")

    def close_leg(reason: str, ts: datetime.datetime) -> None:
        nonlocal current, day_pnl
        c = current
        if c is None:
            return
        ltp = _get_ltp(opt_idx, c["sid"], ts)
        if ltp is None or ltp <= 0:
            current = None
            return
        qty = c["lots"] * LOT_SIZE
        pnl = (c["avg_entry"] - ltp) * Decimal(qty)
        day_pnl += pnl
        trades.append({
            "entry_ts": c["entry_ts"],
            "exit_ts": _as_ist(ts).strftime("%H:%M"),
            "sid": c["sid"],
            "sym": instruments.get(c["sid"], {}).get("trading_symbol", c["sid"]),
            "lots": c["lots"],
            "entry_px": float(c["avg_entry"]),
            "exit_px": float(ltp),
            "pnl": float(pnl),
            "reason": reason,
        })
        current = None

    for bar in nifty_bars:
        ts = bar["ts"]
        ist = _as_ist(ts)
        t = ist.time()
        st = tracker.update(bar["high"], bar["low"], bar["close"], ts)
        if st is None:
            continue

        if t >= SQUAREOFF_IST:
            if current is not None:
                close_leg("square_off", ts)
            done = True
            break

        if done or t < START_IST:
            continue

        if day_pnl <= -DAY_STOP:
            if current is not None:
                close_leg("day_stop", ts)
            done = True
            break

        # Per-leg stop
        if current is not None:
            ltp = _get_ltp(opt_idx, current["sid"], ts)
            if ltp and ltp > 0:
                qty = current["lots"] * LOT_SIZE
                mtm = (current["avg_entry"] - ltp) * Decimal(qty)
                limit = LEG_STOP_PER_LOT * current["lots"]
                if mtm <= -limit:
                    close_leg("leg_stop", ts)
                    continue

        desired = "PE" if st.direction > 0 else "CE"

        if current is None:
            sid = _resolve_option(instruments, desired, Decimal(str(bar["close"])))
            if sid is None:
                continue
            ltp = _get_ltp(opt_idx, sid, ts)
            if ltp is None or ltp <= 0:
                continue
            current = {
                "sid": sid,
                "option_type": desired,
                "lots": START_LOTS,
                "avg_entry": ltp,
                "entry_ts": ist.strftime("%H:%M"),
            }
        elif current["option_type"] != desired:
            close_leg("flip", ts)
            sid = _resolve_option(instruments, desired, Decimal(str(bar["close"])))
            if sid is None:
                continue
            ltp = _get_ltp(opt_idx, sid, ts)
            if ltp is None or ltp <= 0:
                continue
            current = {
                "sid": sid,
                "option_type": desired,
                "lots": START_LOTS,
                "avg_entry": ltp,
                "entry_ts": ist.strftime("%H:%M"),
            }
        elif current["lots"] < MAX_LOTS:
            ltp = _get_ltp(opt_idx, current["sid"], ts)
            if ltp and ltp > 0:
                old_qty = current["lots"] * LOT_SIZE
                add_qty = ADD_LOTS * LOT_SIZE
                total_qty = old_qty + add_qty
                current["avg_entry"] = (current["avg_entry"] * old_qty + ltp * add_qty) / Decimal(total_qty)
                current["lots"] += ADD_LOTS

    if current is not None:
        if nifty_bars:
            close_leg("eod_close", nifty_bars[-1]["ts"])

    return trades, day_pnl


# ---- output ----

def _pct(wins: int, total: int) -> str:
    return f"{wins / total * 100:.0f}%" if total else "N/A"


def print_report(
    date_ist: datetime.date,
    trades: list[dict],
    day_pnl: Decimal,
    paper: dict | None,
    instruments: dict[str, dict],
) -> None:
    print()
    print(f"{'=' * 66}")
    print(f"  BACKTEST vs PAPER  —  {date_ist}  (supertrend_short)")
    print(f"{'=' * 66}")

    # --- trade log ---
    print()
    print("BACKTEST TRADE LOG")
    print(f"  {'Entry':>5}  {'Exit':>5}  {'Symbol':<28}  {'L':>2}  {'Entry':>7}  {'Exit':>7}  {'P&L':>9}  Reason")
    print(f"  {'-'*5}  {'-'*5}  {'-'*28}  {'-'*2}  {'-'*7}  {'-'*7}  {'-'*9}  {'-'*8}")
    for t in trades:
        sym = t["sym"][:28]
        print(
            f"  {t['entry_ts']:>5}  {t['exit_ts']:>5}  {sym:<28}  {t['lots']:>2}  "
            f"{t['entry_px']:>7.2f}  {t['exit_px']:>7.2f}  {t['pnl']:>+9.2f}  {t['reason']}"
        )
    if not trades:
        print("  (no trades)")

    # --- compute backtest stats ---
    bt_wins = sum(1 for t in trades if t["pnl"] > 0)
    bt_losses = sum(1 for t in trades if t["pnl"] <= 0)
    bt_gross_sold = sum(
        t["entry_px"] * t["lots"] * LOT_SIZE for t in trades
    )
    bt_gross_bought = sum(
        t["exit_px"] * t["lots"] * LOT_SIZE for t in trades
    )
    bt_net_pnl = float(day_pnl)

    # --- paper stats ---
    if paper:
        ps = paper.get("stats", {})
        p_trades = ps.get("round_trips", 0)
        p_wins = ps.get("wins", 0)
        p_losses = ps.get("losses", 0)
        p_gross_sold = ps.get("gross_premium_sold", 0.0)
        p_gross_bought = ps.get("gross_premium_bought", 0.0)
        p_net_pnl = ps.get("realized_pnl", 0.0)
    else:
        p_trades = p_wins = p_losses = 0
        p_gross_sold = p_gross_bought = p_net_pnl = 0.0

    # --- summary table ---
    print()
    print("SUMMARY")
    hdr = f"  {'Metric':<22}  {'Backtest':>12}  {'Paper':>12}  {'Delta':>12}"
    print(hdr)
    print(f"  {'-'*22}  {'-'*12}  {'-'*12}  {'-'*12}")

    def row(label: str, bv, pv, fmt: str = ".2f") -> None:
        if isinstance(bv, float) or isinstance(bv, int):
            delta = bv - pv
            print(f"  {label:<22}  {bv:>12{fmt}}  {pv:>12{fmt}}  {delta:>+12{fmt}}")
        else:
            print(f"  {label:<22}  {str(bv):>12}  {str(pv):>12}  {'—':>12}")

    row("Round trips", len(trades), p_trades, "d")
    row("Wins", bt_wins, p_wins, "d")
    row("Losses", bt_losses, p_losses, "d")
    print(f"  {'Win rate':<22}  {_pct(bt_wins, len(trades)):>12}  {_pct(p_wins, p_trades):>12}  {'—':>12}")
    row("Gross sold (INR)", bt_gross_sold, p_gross_sold)
    row("Gross bought (INR)", bt_gross_bought, p_gross_bought)
    row("Net P&L (INR)", bt_net_pnl, p_net_pnl)
    print()

    if paper is None:
        print("  [NOTE] No paper_journal entry found for this date.")
    print(f"{'=' * 66}")
    print()


# ---- main ----

def parse_args() -> argparse.Namespace:
    today_ist = datetime.datetime.now(_IST).date()
    p = argparse.ArgumentParser(description="Backtest vs paper comparison")
    p.add_argument(
        "--date",
        default=today_ist.isoformat(),
        help="IST trading date (YYYY-MM-DD, default: today)",
    )
    return p.parse_args()


async def _fetch_instruments_for_options(opt_sids: list[str]) -> dict[str, dict]:
    return await _load_instruments(opt_sids)


def main() -> None:
    args = parse_args()
    try:
        date_ist = datetime.date.fromisoformat(args.date)
    except ValueError:
        print(f"Invalid date: {args.date}. Use YYYY-MM-DD.")
        sys.exit(1)

    mongo = MongoClient(_MONGO_URI)
    db = mongo[_MONGO_DB]

    start_utc, end_utc = _utc_window(date_ist)
    prior_start, prior_end = _prior_utc_window(date_ist)

    # Load NIFTY 5m bars
    nifty_bars = _load_bars(db, NIFTY_SID, TIMEFRAME, start_utc, end_utc)
    if not nifty_bars:
        print(f"No market bars found for {date_ist}.")
        sys.exit(1)

    print(f"Loaded {len(nifty_bars)} NIFTY {TIMEFRAME} bars for {date_ist}.")

    # Load prior-session bars to seed the SuperTrend tracker (warm-up only, no trading)
    prior_bars = _load_bars(db, NIFTY_SID, TIMEFRAME, prior_start, prior_end)
    seed_bars = prior_bars[-(ST_PERIOD + 2):] if prior_bars else []
    if seed_bars:
        print(f"Pre-seeding SuperTrend with {len(seed_bars)} prior-session bars.")

    # Discover which option security_ids appear in today's bars
    opt_sids_in_mongo = list(
        {
            b["metadata"]["security_id"]
            for b in db["market_bars"].find(
                {"metadata.timeframe": TIMEFRAME, "ts": {"$gte": start_utc, "$lte": end_utc}},
                {"metadata.security_id": 1, "_id": 0},
            )
            if b["metadata"]["security_id"] != NIFTY_SID
        }
    )

    if not opt_sids_in_mongo:
        print("No option bars found for this date. Cannot simulate fills.")
        sys.exit(1)

    print(f"Found option bars for {len(opt_sids_in_mongo)} instruments.")

    # Load instrument metadata and option bar prices
    instruments = asyncio.run(_fetch_instruments_for_options(opt_sids_in_mongo))
    opt_idx = _opt_price_index(db, opt_sids_in_mongo, start_utc, end_utc)

    # Run simulation — seed_bars warm the tracker; nifty_bars are today's session
    trades, day_pnl = simulate(nifty_bars, opt_idx, instruments, seed_bars=seed_bars)

    # Load paper journal
    paper_doc = db["paper_journal"].find_one({"date": date_ist.isoformat()})

    print_report(date_ist, trades, day_pnl, paper_doc, instruments)


if __name__ == "__main__":
    main()
