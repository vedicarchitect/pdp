"""
Full-day backtest for supertrend_short — 2026-06-08.

Fetches 5m intraday bars for all Jun9 NIFTY option strikes from Dhan API,
runs SuperTrend(3,1) on NIFTY 5m, simulates every leg the strategy would
have taken, and computes P&L using real market prices.
"""
import sys, os, time
sys.path.insert(0, 'src')
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from dhanhq import DhanContext, dhanhq
from pdp.indicators.supertrend import SuperTrendTracker

IST     = timedelta(hours=5, minutes=30)
LOT     = 65
STRIKE_STEP = 50
OTM_STEPS   = 1

# ── Dhan client ───────────────────────────────────────────────────────────────
CLIENT_ID    = os.environ["DHAN_CLIENT_ID"]
ACCESS_TOKEN = os.environ["DHAN_ACCESS_TOKEN"]
ctx    = DhanContext(CLIENT_ID, ACCESS_TOKEN)
client = dhanhq(ctx)

# ── Security ID map for Jun9 NIFTY options we may need ───────────────────────
# strike -> {CE: sid, PE: sid}
STRIKES = {
    23050: {"CE": 42270, "PE": 42271},
    23100: {"CE": 42272, "PE": 42273},
    23150: {"CE": 42278, "PE": 42279},
    23200: {"CE": 42284, "PE": 42285},
    23250: {"CE": 42286, "PE": 42287},
    23300: {"CE": 42288, "PE": 42289},
    23350: {"CE": 42290, "PE": 42293},
}

TODAY = "2026-06-08"

# ── 1. Load NIFTY 5m bars from MongoDB ───────────────────────────────────────
uri     = os.environ.get("MONGO_URI",    "mongodb://localhost:27017")
db_name = os.environ.get("MONGO_DB_NAME","pdp")
mdb     = MongoClient(uri)[db_name]

start_utc = datetime(2026, 6, 8, 3, 30, tzinfo=timezone.utc)
end_utc   = datetime(2026, 6, 8, 10, 5,  tzinfo=timezone.utc)

raw = list(mdb["market_bars"].find({
    "metadata.security_id": "13",
    "metadata.timeframe": "5m",
    "ts": {"$gte": start_utc, "$lte": end_utc},
}).sort("ts", 1))

seen, nifty_bars = set(), []
for b in raw:
    key = b["ts"].replace(second=0, microsecond=0)
    if key not in seen:
        seen.add(key)
        nifty_bars.append(b)

print(f"NIFTY bars: {len(nifty_bars)} unique (raw {len(raw)})")

# ── 2. Compute SuperTrend(3,1) ────────────────────────────────────────────────
tracker   = SuperTrendTracker(period=3, multiplier=1)
st_series = []
for b in nifty_bars:
    ist_dt = (b["ts"] + IST).replace(tzinfo=None)
    state  = tracker.update(b["high"], b["low"], b["close"], bar_time=b["ts"])
    st_series.append((ist_dt, float(b["close"]), state))

# ── 3. Determine which option legs the strategy would have taken ──────────────
START_IST  = datetime(2026, 6, 8,  9, 30)
SQOFF_IST  = datetime(2026, 6, 8, 15, 10)

def otm_strike(spot, opt_type):
    base = round(spot / STRIKE_STEP) * STRIKE_STEP
    return base - OTM_STEPS * STRIKE_STEP if opt_type == "PE" else base + OTM_STEPS * STRIKE_STEP

sim_legs = []
cur       = None

for ist_dt, close, st in st_series:
    if st is None:
        continue
    if ist_dt < START_IST:
        continue
    if ist_dt >= SQOFF_IST:
        if cur:
            cur["exit_bar"] = ist_dt
            cur["reason"]   = "squareoff"
            sim_legs.append(cur); cur = None
        break
    desired = "PE" if st.direction > 0 else "CE"
    if cur is None:
        cur = {"type": desired, "entry_bar": ist_dt,
               "strike": otm_strike(close, desired), "entry_nifty": close, "bars": 1}
    elif cur["type"] != desired:
        cur["exit_bar"] = ist_dt; cur["reason"] = "flip"
        sim_legs.append(cur)
        cur = {"type": desired, "entry_bar": ist_dt,
               "strike": otm_strike(close, desired), "entry_nifty": close, "bars": 1}
    else:
        cur["bars"] += 1

if cur:
    cur["exit_bar"] = SQOFF_IST; cur["reason"] = "squareoff"
    sim_legs.append(cur)

print(f"\nSimulated legs: {len(sim_legs)}")

# ── 4. Fetch 5m option bars from Dhan for each unique security ────────────────
needed_sids = set()
for leg in sim_legs:
    strike = int(leg["strike"])
    if strike in STRIKES:
        needed_sids.add(STRIKES[strike][leg["type"]])
    else:
        print(f"  WARNING: strike {strike} not in STRIKES map")

print(f"Fetching 5m bars from Dhan for {len(needed_sids)} option sids: {sorted(needed_sids)}")

opt_bars = {}  # sid -> list of (ist_dt, open, high, low, close)
for sid in sorted(needed_sids):
    print(f"  Fetching sid={sid} ...", end=" ", flush=True)
    try:
        resp = client.intraday_minute_data(
            security_id=str(sid),
            exchange_segment="NSE_FNO",
            instrument_type="OPTIDX",
            from_date=TODAY,
            to_date=TODAY,
            interval=5,
        )
        time.sleep(0.5)  # rate-limit
        if isinstance(resp, dict) and resp.get("status") == "success":
            data = resp.get("data", {})
            # SDK may wrap in another 'data' key
            if isinstance(data, dict) and "open" not in data and "data" in data:
                data = data["data"]
            # data should have keys: open, high, low, close, volume, timestamp
            if isinstance(data, dict) and "open" in data:
                opens  = data["open"]
                highs  = data["high"]
                lows   = data["low"]
                closes = data["close"]
                timestamps = data.get("timestamp", data.get("start_Time", []))
                bars_out = []
                for i in range(len(closes)):
                    ts_raw = timestamps[i]
                    # Parse timestamp — could be epoch int or ISO string
                    if isinstance(ts_raw, (int, float)):
                        dt = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                        ist_dt = (dt + IST).replace(tzinfo=None)
                    else:
                        # Try ISO parse
                        try:
                            dt = datetime.fromisoformat(str(ts_raw))
                            if dt.tzinfo is None:
                                ist_dt = dt  # assume already IST
                            else:
                                ist_dt = (dt + IST).replace(tzinfo=None)
                        except Exception:
                            ist_dt = None
                    if ist_dt and closes[i] and closes[i] > 0:
                        bars_out.append((ist_dt, float(opens[i]), float(highs[i]),
                                         float(lows[i]), float(closes[i])))
                opt_bars[sid] = sorted(bars_out)
                print(f"OK ({len(bars_out)} bars)")
            else:
                print(f"EMPTY (data keys: {list(data.keys()) if isinstance(data, dict) else type(data)})")
                opt_bars[sid] = []
        else:
            print(f"FAILED: {str(resp)[:120]}")
            opt_bars[sid] = []
    except Exception as e:
        print(f"ERROR: {e}")
        opt_bars[sid] = []

# ── 5. Helper: get option price at a given bar time ──────────────────────────
def price_at(sid, target_dt, prefer="open"):
    """
    Return option price at target_dt.
    prefer='open' = opening price of the bar that starts at/after target_dt (simulates fill on next bar open)
    prefer='close' = closing price of the bar at target_dt
    """
    bars = opt_bars.get(sid, [])
    if not bars:
        return None
    # Find the bar closest to target_dt
    best = None
    best_delta = timedelta(hours=99)
    for (dt, o, h, l, c) in bars:
        delta = abs(dt - target_dt)
        if delta < best_delta:
            best_delta = delta
            best = (dt, o, h, l, c)
    if best is None or best_delta > timedelta(minutes=15):
        return None
    return best[1] if prefer == "open" else best[4]  # open or close

# ── 6. Compute P&L per leg ────────────────────────────────────────────────────
print()
print("=" * 100)
print(f"  FULL-DAY BACKTEST P&L  --  2026-06-08  SuperTrend(3,1) NIFTY  |  OTM=1  |  2->5 lots")
print("=" * 100)
print(f"  {'#':>2}  {'Entry':>5}  {'Exit':>5}  {'Reason':<11}  {'Type':<3}  {'Strike':>6}  "
      f"{'Lots':>5}  {'AvgEntry':>9}  {'ExitPx':>7}  {'Net Prem':>10}  {'P&L':>8}")
print("-" * 100)

total_pnl = 0.0
pnl_unavail = 0

for i, leg in enumerate(sim_legs, 1):
    strike  = int(leg["strike"])
    opt_type = leg["type"]
    entry_bar = leg["entry_bar"]
    exit_bar  = leg["exit_bar"]

    if strike not in STRIKES:
        print(f"  {i:>2}  {entry_bar.strftime('%H:%M'):>5}  {exit_bar.strftime('%H:%M'):>5}  "
              f"{leg['reason']:<11}  {opt_type:<3}  {strike:>6}  -- strike not mapped --")
        pnl_unavail += 1
        continue

    sid = STRIKES[strike][opt_type]

    # Entry price: open of the bar after entry signal (next bar open)
    # Exit price: open of bar after exit signal (flip/squareoff triggers at bar close)
    entry_px = price_at(sid, entry_bar, prefer="open")
    exit_px  = price_at(sid, exit_bar,  prefer="open")

    # Lot scaling: start 2 lots, add 1 per bar up to 5
    bars_in_leg = leg["bars"]
    lots = min(2 + (bars_in_leg - 1), 5)  # approximate: each bar adds 1 lot

    if entry_px and exit_px:
        qty        = lots * LOT
        net_prem   = (entry_px - exit_px) * qty  # short: profit when premium falls
        total_pnl += net_prem
        direction  = "PROFIT" if net_prem > 0 else "LOSS"
        print(f"  {i:>2}  {entry_bar.strftime('%H:%M'):>5}  {exit_bar.strftime('%H:%M'):>5}  "
              f"{leg['reason']:<11}  {opt_type:<3}  {strike:>6}  {lots:>5}L  "
              f"{entry_px:>9.2f}  {exit_px:>7.2f}  {net_prem:>+10.2f}  {direction}")
    else:
        avail = "no_entry" if not entry_px else "no_exit"
        print(f"  {i:>2}  {entry_bar.strftime('%H:%M'):>5}  {exit_bar.strftime('%H:%M'):>5}  "
              f"{leg['reason']:<11}  {opt_type:<3}  {strike:>6}  {lots:>5}L  "
              f"  [sid={sid}  {avail}]")
        pnl_unavail += 1

print("-" * 100)
est_charges = len(sim_legs) * 2 * 7.25  # rough: ~Rs 7.25 per side per leg
print(f"  {'Total net premium':>55}  {total_pnl:>+10.2f}")
print(f"  {'Est. charges (STT+brok+stamp, ~Rs7.25/side)':>55}  {-est_charges:>+10.2f}")
print(f"  {'Realized P&L':>55}  {total_pnl - est_charges:>+10.2f}")
if pnl_unavail:
    print(f"\n  NOTE: {pnl_unavail} leg(s) have missing price data (shown above with [sid=...])")
print()

# ── 7. Print raw option bar availability summary ──────────────────────────────
print("  OPTION BAR AVAILABILITY")
print("-" * 60)
for sid in sorted(needed_sids):
    bars = opt_bars.get(sid, [])
    if bars:
        first = bars[0][0].strftime("%H:%M")
        last  = bars[-1][0].strftime("%H:%M")
        print(f"  sid={sid}  bars={len(bars):>3}  {first} -> {last}")
    else:
        print(f"  sid={sid}  NO DATA")
print("=" * 100)
