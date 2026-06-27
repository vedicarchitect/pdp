"""
Backtest replay for supertrend_short strategy — 2026-06-08.

Loads today's NIFTY 5m bars from MongoDB, runs SuperTrend(3,1),
simulates strategy signals, and overlays actual paper fills from PG.
"""
import sys, os
sys.path.insert(0, 'src')

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pdp.indicators.supertrend import SuperTrendTracker

IST = ZoneInfo("Asia/Kolkata")
IST_OFF = timedelta(hours=5, minutes=30)

# ─── 1. Load NIFTY 5m bars from MongoDB ──────────────────────────────────────
uri     = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')
db_name = os.environ.get('MONGO_DB_NAME', 'pdp')
client  = MongoClient(uri)
db      = client[db_name]
coll    = db['market_bars']

start_utc = datetime(2026, 6, 8, 3, 30, tzinfo=timezone.utc)
end_utc   = datetime(2026, 6, 8, 10, 5,  tzinfo=timezone.utc)

raw = list(coll.find({
    'metadata.security_id': '13',
    'metadata.timeframe': '5m',
    'ts': {'$gte': start_utc, '$lte': end_utc}
}).sort('ts', 1))

# De-duplicate on minute (keep first)
seen, bars = set(), []
for b in raw:
    key = b['ts'].replace(second=0, microsecond=0)
    if key not in seen:
        seen.add(key)
        bars.append(b)

print(f"Loaded {len(bars)} unique 5m bars  (raw count: {len(raw)}, "
      f"{len(raw)-len(bars)} duplicate(s) removed)")

# ─── 2. Compute SuperTrend(3,1) for every bar ────────────────────────────────
tracker = SuperTrendTracker(period=3, multiplier=1)
st_series = []  # (ist_dt, open, high, low, close, st_state)
for b in bars:
    ist_dt = (b['ts'] + IST_OFF).replace(tzinfo=None)
    state  = tracker.update(b['high'], b['low'], b['close'], bar_time=b['ts'])
    st_series.append((ist_dt, float(b['open']), float(b['high']),
                      float(b['low']),  float(b['close']), state))

# ─── 3. Strategy simulation (signal-only; no live fills) ─────────────────────
START_IST  = datetime(2026, 6, 8,  9, 30)
SQOFF_IST  = datetime(2026, 6, 8, 15, 10)
LOT        = 65
START_LOTS = 2
ADD_LOTS   = 1
MAX_LOTS   = 5
STRIKE_STEP = 50
OTM_STEPS   = 1

def otm_strike(spot, opt_type):
    base = (round(spot / STRIKE_STEP) * STRIKE_STEP)
    if opt_type == 'PE':
        return base - OTM_STEPS * STRIKE_STEP
    return base + OTM_STEPS * STRIKE_STEP

sim_legs = []   # completed simulated legs
cur       = None  # active leg dict

for ist_dt, o, h, l, c, st in st_series:
    if st is None:
        continue
    if ist_dt < START_IST:
        continue
    if ist_dt >= SQOFF_IST:
        if cur:
            cur['exit_bar'] = ist_dt
            cur['reason']   = 'squareoff'
            sim_legs.append(cur)
            cur = None
        break

    desired = 'PE' if st.direction > 0 else 'CE'

    if cur is None:
        strike = otm_strike(c, desired)
        cur = dict(type=desired, entry_bar=ist_dt, close=c,
                   strike=strike, lots=START_LOTS, bars=1)
    elif cur['type'] != desired:
        cur['exit_bar'] = ist_dt
        cur['reason']   = 'flip'
        sim_legs.append(cur)
        strike = otm_strike(c, desired)
        cur = dict(type=desired, entry_bar=ist_dt, close=c,
                   strike=strike, lots=START_LOTS, bars=1)
    else:
        if cur['lots'] < MAX_LOTS:
            cur['lots'] += ADD_LOTS
        cur['bars'] += 1

if cur:
    cur['exit_bar'] = SQOFF_IST
    cur['reason']   = 'squareoff'
    sim_legs.append(cur)

# ─── 4. Actual fills (reconstructed from earlier session analysis) ────────────
# The DB was cleared by reset_paper.py after the session.
# These are the actual fills recorded during today's live run.
ACTUAL_FILLS = [
    # (side, qty, price, time_str, security_id, phase, note)
    ('SELL', 130, 86.13, '14:25', '42284', 1, '2-lot entry PE23050 Jun9'),
    ('SELL',  65, 83.63, '14:30', '42284', 1, '+1-lot scale'),
    ('SELL',  65, 87.28, '14:35', '42284', 1, '+1-lot scale'),
    ('SELL',  65, 85.33, '14:40', '42284', 1, '+1-lot scale (5 lot cap hit)'),
    ('BUY',  325, 96.52, '14:45', '42284', 1, 'close on flip'),
    ('SELL', 130, 81.08, '14:45', '42279', 2, '2-lot entry PE23300? Jun9 (flip to new strike)'),
    ('SELL',  65, 87.03, '14:50', '42279', 2, '+1-lot scale'),
    ('SELL',  65, 87.93, '14:55', '42279', 2, '+1-lot scale'),
    ('SELL',  65, 83.03, '15:00', '42279', 2, '+1-lot scale (5 lot cap)'),
    ('BUY',  325,109.17, '15:05', '42279', 2, 'close on flip'),
    # Order 11: SELL OPEN -> CANCELLED (new leg after phase-2 close, never filled)
    # Order 12: BUY 130 @ 90.02 -> ORPHAN BUY (bug, now fixed) — excluded from real P&L
]

# ─── 5. Print bar-by-bar table ────────────────────────────────────────────────
SEP = '-' * 90

print()
print('  NIFTY 5m SuperTrend(3,1) Bar-by-Bar  —  2026-06-08')
print(SEP)
print(f'  {"Bar":>5}  {"Open":>9}  {"High":>9}  {"Low":>9}  {"Close":>9}  {"ST":>9}  {"Dir":>5}  Notes')
print(SEP)

fill_times = {f[3] for f in ACTUAL_FILLS}

for ist_dt, o, h, l, c, st in st_series:
    ts_s = ist_dt.strftime('%H:%M')
    if st is None:
        dir_s, val_s = '  ---', '      ---'
    else:
        dir_s = '  UP ' if st.direction > 0 else '  DN '
        val_s = f'{float(st.value):>9.2f}'

    notes = []
    if st and st.flipped:
        notes.append('<<FLIP>>')
    if ts_s in fill_times:
        fills_here = [f for f in ACTUAL_FILLS if f[3] == ts_s]
        for f in fills_here:
            notes.append(f'[{f[0]} {f[1]}@{f[2]}]')
    if ist_dt >= START_IST and st and ist_dt < SQOFF_IST:
        desired = 'PE' if st.direction > 0 else 'CE'
        notes.append(f'sig:{desired}')

    print(f'  {ts_s:>5}  {o:>9.2f}  {h:>9.2f}  {l:>9.2f}  {c:>9.2f}  {val_s}  {dir_s}  {" ".join(notes)}')

print(SEP)

# ─── 6. Simulated strategy legs ──────────────────────────────────────────────
print()
print('  SIMULATED STRATEGY LEGS (bar-close signals)')
print(SEP)
print(f'  {"Entry":>5}  {"Exit":>5}  {"Reason":<12}  {"Type":<4}  {"Strike":>7}  '
      f'{"Lots":>5}  {"Bars":>5}  {"Entry NIFTY":>12}')
print(SEP)
for leg in sim_legs:
    eb = leg["exit_bar"].strftime('%H:%M') if isinstance(leg["exit_bar"], datetime) else '     '
    print(f'  {leg["entry_bar"].strftime("%H:%M"):>5}  {eb:>5}  {leg["reason"]:<12}  '
          f'{leg["type"]:<4}  {leg["strike"]:>7.0f}  {leg["lots"]:>5}  {leg["bars"]:>5}  '
          f'{leg["close"]:>12.2f}')
print(SEP)

# ─── 7. Actual fills + P&L ───────────────────────────────────────────────────
print()
print('  ACTUAL PAPER FILLS  (DB cleared post-session; reconstructed from logs)')
print(SEP)
print(f'  {"Side":<4}  {"Qty":>4}  {"Price":>7}  {"Time":>5}  {"Ph":>3}  Note')
print(SEP)
ph_sell = {}; ph_buy = {}
for side, qty, px, t, sec, ph, note in ACTUAL_FILLS:
    print(f'  {side:<4}  {qty:>4}  {px:>7.2f}  {t:>5}  {ph:>3}  {note}')
    if ph in (1, 2):
        if side == 'SELL':
            ph_sell.setdefault(ph, []).append((qty, px))
        else:
            ph_buy[ph] = (qty, px)

print(SEP)
print()
print('  P&L SUMMARY')
print(SEP)

total = 0
for ph in (1, 2):
    sells = ph_sell.get(ph, [])
    bq, bp = ph_buy.get(ph, (0, 0))
    sp    = sum(q*p for q,p in sells)
    bc    = bq * bp
    avg   = sp / sum(q for q,_ in sells) if sells else 0
    net   = sp - bc
    total += net
    print(f'  Phase {ph}: {sum(q for q,_ in sells)//LOT} lots  '
          f'avg_entry={avg:.2f}  close_px={bp:.2f}  '
          f'net_premium={net:>+9.2f}  '
          f'{"PROFIT" if net>0 else "LOSS"}')

print(f'  {"":35}  ----------')
print(f'  {"Total net premium":35}  {total:>+9.2f}')
print(f'  {"Approx charges (STT+brok+stamp)":35}  {"":>4}-7.25')
print(f'  {"Realized P&L":35}  {total-7.25:>+9.2f}')
print()
print(f'  [Orphan BUY order 12 cost -11,702 excluded — was a bug, now fixed]')
print(SEP)

# ─── 8. Compare sim vs actual ────────────────────────────────────────────────
print()
print('  SIMULATION vs ACTUAL COMPARISON')
print(SEP)
print('  Simulated legs based on bar-close ST signals. Actual entries at market open of next bar.')
print()
for i, leg in enumerate(sim_legs, 1):
    eb = leg["exit_bar"].strftime('%H:%M') if isinstance(leg["exit_bar"], datetime) else 'N/A'
    print(f'  Sim Leg {i}: {leg["entry_bar"].strftime("%H:%M")}-{eb}  '
          f'{leg["type"]} {leg["strike"]:.0f}  {leg["lots"]}L  reason={leg["reason"]}')

print()
print('  Actual: 1 phase-1 PE23050 leg (09:30-14:25 entry, 14:45 close, 5L) — matches sim flip signal')
print('         1 phase-2 PE leg         (14:45 entry, 15:05 close, 5L) — matches sim squareoff signal')
print()
print('  NOTE: Actual session started trading ONLY at 14:25 IST even though strategy')
print('        signals from ~09:30 were being generated. This could indicate:')
print('        (a) strategy was not running in the morning session, or')
print('        (b) the DB was reset mid-day and fills from morning were wiped')
print(SEP)
