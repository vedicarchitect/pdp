"""
Multi-day backtest: SuperTrend(3,1) NIFTY option-selling with risk management.

Risk rules:
  - LEG STOP  : if current open position MTM loss >= 5,000  -> close at bar close price
  - DAY STOP  : if cumulative realized day loss >= 10,000   -> flat + no more trades today

Usage:
  python backtest_multiday.py              # last 7 business days
  python backtest_multiday.py --days 14
  python backtest_multiday.py --days 3 --start 2026-06-01
"""
import sys, os, time, argparse
sys.path.insert(0, "src")
from dotenv import load_dotenv; load_dotenv()

from datetime import datetime, date, timedelta, timezone
from dataclasses import dataclass, field

# ── CLI ───────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument("--days",  type=int,  default=7)
ap.add_argument("--start", type=str,  default=None,
                help="End date YYYY-MM-DD (default: 2026-06-08)")
args = ap.parse_args()

# ── Strategy constants ────────────────────────────────────────────────────────
LOT          = 65
START_LOTS   = 2
ADD_LOTS     = 1
MAX_LOTS     = 5
STRIKE_STEP  = 50
OTM_STEPS    = 1
START_H, START_M  = 9,  30
SQOFF_H, SQOFF_M  = 15, 10
LEG_STOP_PER_LOT = 1_000.0  # close if MTM loss >= this × current lots
DAY_STOP_LOSS    = 10_000.0  # no more trades if realized day loss >= this
IST = timedelta(hours=5, minutes=30)

# ── Imports ───────────────────────────────────────────────────────────────────
from pymongo import MongoClient
import psycopg
from dhanhq import DhanContext, dhanhq
from pdp.indicators.supertrend import SuperTrendTracker

mdb = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017"))[
    os.environ.get("MONGO_DB_NAME", "pdp")]

pg_url = (os.environ["DATABASE_URL"]
          .replace("postgresql+asyncpg://", "postgresql://")
          .replace("postgresql+psycopg://",  "postgresql://"))
pg = psycopg.connect(pg_url)

dhan = dhanhq(DhanContext(os.environ["DHAN_CLIENT_ID"],
                           os.environ["DHAN_ACCESS_TOKEN"]))

# ── Helpers ───────────────────────────────────────────────────────────────────
def biz_days(end: date, n: int):
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5: days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))

def otm_strike(spot, opt_type):
    base = round(spot / STRIKE_STEP) * STRIKE_STEP
    return int(base - OTM_STEPS * STRIKE_STEP if opt_type == "PE"
               else base + OTM_STEPS * STRIKE_STEP)

def price_at(bars, target, prefer="open"):
    best, bd = None, timedelta(hours=99)
    for (dt, o, h, l, c) in bars:
        d = abs(dt - target)
        if d < bd: bd, best = d, (dt, o, h, l, c)
    if best is None or bd > timedelta(minutes=15): return None
    return best[1] if prefer == "open" else best[4]

# ── Instrument / bar caches ───────────────────────────────────────────────────
_inst:  dict[str, dict]   = {}
_bars:  dict[tuple, list] = {}

def inst_map(expiry_str):
    if expiry_str not in _inst:
        cur = pg.execute("SELECT security_id,strike,option_type FROM instruments "
                         "WHERE underlying='NIFTY' AND expiry=%s", (expiry_str,))
        _inst[expiry_str] = {(int(r[1]), r[2]): int(r[0]) for r in cur.fetchall()}
    return _inst[expiry_str]

def active_expiry(d: date):
    cur = pg.execute("SELECT DISTINCT expiry FROM instruments "
                     "WHERE underlying='NIFTY' AND expiry>=%s ORDER BY expiry LIMIT 1",
                     (d.isoformat(),))
    r = cur.fetchone()
    return r[0].isoformat() if r else None

def _parse_dhan_bars(data):
    opens = data["open"]; highs = data["high"]; lows = data["low"]
    closes = data["close"]
    tss = data.get("timestamp", data.get("start_Time", []))
    out = []
    for i in range(len(closes)):
        if not closes[i]: continue
        ts = tss[i]
        if isinstance(ts, (int, float)):
            dt = (datetime.fromtimestamp(ts, tz=timezone.utc) + IST).replace(tzinfo=None)
        else:
            try:
                dt = datetime.fromisoformat(str(ts))
                if dt.tzinfo: dt = (dt + IST).replace(tzinfo=None)
            except: continue
        if dt and closes[i] > 0:
            out.append((dt, float(opens[i]), float(highs[i]),
                        float(lows[i]), float(closes[i])))
    return sorted(out)

def fetch_bars(sid, date_str, seg, itype):
    k = (sid, date_str)
    if k in _bars: return _bars[k]
    try:
        r = dhan.intraday_minute_data(security_id=str(sid), exchange_segment=seg,
                                      instrument_type=itype, from_date=date_str,
                                      to_date=date_str, interval=5)
        time.sleep(0.4)
    except Exception as e:
        _bars[k] = []; return []
    if not (isinstance(r, dict) and r.get("status") == "success"):
        _bars[k] = []; return []
    data = r.get("data", {})
    if isinstance(data, dict) and "data" in data and "open" not in data:
        data = data["data"]
    if not (isinstance(data, dict) and "open" in data):
        _bars[k] = []; return []
    _bars[k] = _parse_dhan_bars(data)
    return _bars[k]

def fetch_nifty(date_str):
    return fetch_bars("13", date_str, "IDX_I", "INDEX")

def fetch_opt(sid, date_str):
    return fetch_bars(sid, date_str, "NSE_FNO", "OPTIDX")

# ── Position tracker ──────────────────────────────────────────────────────────
@dataclass
class Position:
    opt_type:   str
    strike:     int
    sid:        int
    total_qty:  int   = 0
    total_cost: float = 0.0
    lots:       int   = 0

    def add(self, qty, px):
        self.total_qty  += qty
        self.total_cost += px * qty
        self.lots        = self.total_qty // LOT

    @property
    def avg_entry(self): return self.total_cost / self.total_qty if self.total_qty else 0.0

    def mtm(self, current_px): return (self.avg_entry - current_px) * self.total_qty

# ── Trade record ──────────────────────────────────────────────────────────────
@dataclass
class Trade:
    side:        str     # SELL / BUY
    opt_type:    str
    strike:      int
    bar_time:    datetime
    qty:         int
    price:       float
    nifty:       float
    note:        str     = ""
    cum_lots:    int     = 0
    avg_entry:   float   = 0.0
    leg_pnl:     float | None = None  # only set on close trades
    day_pnl:     float   = 0.0

# ── Per-day simulation ─────────────────────────────────────────────────────────
def simulate_day(trade_date: date):
    ds = trade_date.isoformat()
    st_ut = datetime(trade_date.year, trade_date.month, trade_date.day, 3, 30, tzinfo=timezone.utc)
    en_ut = datetime(trade_date.year, trade_date.month, trade_date.day, 10, 5,  tzinfo=timezone.utc)

    # NIFTY bars
    raw = list(mdb["market_bars"].find(
        {"metadata.security_id": "13", "metadata.timeframe": "5m",
         "ts": {"$gte": st_ut, "$lte": en_ut}}).sort("ts", 1))
    seen, nifty_bars = set(), []
    for b in raw:
        k = b["ts"].replace(second=0, microsecond=0)
        if k not in seen: seen.add(k); nifty_bars.append(b)

    if not nifty_bars:
        dhan_bars = fetch_nifty(ds)
        nifty_bars = [{"ts": dt.replace(tzinfo=timezone.utc) - IST,
                       "open": o, "high": h, "low": l, "close": c}
                      for dt, o, h, l, c in dhan_bars]
    if not nifty_bars: return None

    nifty_open  = float(nifty_bars[0]["open"])
    nifty_close = float(nifty_bars[-1]["close"])

    exp = active_expiry(trade_date)
    if not exp: return None
    imap = inst_map(exp)

    # Precompute ST series
    tracker = SuperTrendTracker(period=3, multiplier=1)
    series  = []
    for b in nifty_bars:
        ts_utc = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=timezone.utc)
        ist_dt = (ts_utc + IST).replace(tzinfo=None)
        st = tracker.update(b["high"], b["low"], b["close"], bar_time=ts_utc)
        series.append((ist_dt, float(b["open"]), float(b["close"]), st))

    start_dt = datetime(trade_date.year, trade_date.month, trade_date.day, START_H, START_M)
    sqoff_dt = datetime(trade_date.year, trade_date.month, trade_date.day, SQOFF_H, SQOFF_M)

    # Pre-fetch option bars for all possible strikes
    needed_sids = set(imap.values())
    for sid in needed_sids:
        fetch_opt(sid, ds)

    # ── Bar-by-bar simulation ──────────────────────────────────────────────────
    pos:       Position | None = None
    trades:    list[Trade]     = []
    day_pnl    = 0.0
    done       = False
    stop_reason = ""

    def close_position(ist_dt, nifty_px, close_px, reason):
        nonlocal day_pnl, done, stop_reason, pos
        assert pos is not None
        qty     = pos.total_qty
        leg_pnl = (pos.avg_entry - close_px) * qty
        day_pnl += leg_pnl
        trades.append(Trade(
            side="BUY", opt_type=pos.opt_type, strike=pos.strike,
            bar_time=ist_dt, qty=qty, price=close_px,
            nifty=nifty_px,
            note=reason,
            cum_lots=pos.lots,
            avg_entry=pos.avg_entry,
            leg_pnl=leg_pnl,
            day_pnl=day_pnl,
        ))
        if day_pnl <= -DAY_STOP_LOSS and not done:
            done = True
            stop_reason = f"day_stop ({day_pnl:+.0f})"
        pos = None

    for ist_dt, bar_open, bar_close, st in series:
        if st is None: continue
        if ist_dt < start_dt: continue

        # Square-off
        if ist_dt >= sqoff_dt:
            if pos:
                opt_bars_sq = _bars.get((pos.sid, ds), [])
                sq_px = price_at(opt_bars_sq, ist_dt, prefer="open") or price_at(opt_bars_sq, ist_dt, prefer="close")
                if sq_px:
                    close_position(ist_dt, bar_open, sq_px, "squareoff")
            break

        if done: continue

        desired = "PE" if st.direction > 0 else "CE"

        # ── Check leg stop-loss at bar CLOSE (if position open) ──
        if pos:
            opt_bars_p = _bars.get((pos.sid, ds), [])
            bar_close_px = price_at(opt_bars_p, ist_dt, prefer="close")
            if bar_close_px:
                mtm = pos.mtm(bar_close_px)
                if mtm <= -(LEG_STOP_PER_LOT * pos.lots):
                    limit = LEG_STOP_PER_LOT * pos.lots
                    close_position(ist_dt, bar_close, bar_close_px, f"leg_stop (mtm={mtm:+.0f}, limit={-limit:.0f})")
                    continue   # no new entry on stop bar

        # ── Flip: close current, open new ──
        if pos and pos.opt_type != desired:
            opt_bars_f = _bars.get((pos.sid, ds), [])
            flip_px = price_at(opt_bars_f, ist_dt, prefer="open")
            if flip_px:
                close_position(ist_dt, bar_open, flip_px, "flip")
            else:
                pos = None   # can't price it; clear position
            if done: continue

        # ── Open / scale-in ──
        k = (otm_strike(bar_close, desired), desired)
        sid = imap.get(k)
        if not sid: continue

        opt_bars_n = _bars.get((sid, ds), [])

        if pos is None:
            # New entry
            entry_px = price_at(opt_bars_n, ist_dt, prefer="open")
            if entry_px:
                pos = Position(opt_type=desired, strike=k[0], sid=sid)
                pos.add(START_LOTS * LOT, entry_px)
                trades.append(Trade(
                    side="SELL", opt_type=desired, strike=k[0],
                    bar_time=ist_dt, qty=START_LOTS * LOT, price=entry_px,
                    nifty=bar_close,
                    note=f"open {START_LOTS}L",
                    cum_lots=pos.lots, avg_entry=pos.avg_entry,
                    day_pnl=day_pnl,
                ))
        elif pos.sid == sid and pos.lots < MAX_LOTS:
            # Scale in
            add_px = price_at(opt_bars_n, ist_dt, prefer="open")
            if add_px:
                pos.add(ADD_LOTS * LOT, add_px)
                trades.append(Trade(
                    side="SELL", opt_type=desired, strike=k[0],
                    bar_time=ist_dt, qty=ADD_LOTS * LOT, price=add_px,
                    nifty=bar_close,
                    note=f"scale +{ADD_LOTS}L -> {pos.lots}L",
                    cum_lots=pos.lots, avg_entry=pos.avg_entry,
                    day_pnl=day_pnl,
                ))

    # Unclosed position at end (rare — squareoff loop should handle)
    if pos:
        opt_bars_e = _bars.get((pos.sid, ds), [])
        end_px = (price_at(opt_bars_e, sqoff_dt, prefer="close") or
                  price_at(opt_bars_e, sqoff_dt, prefer="open"))
        if end_px:
            close_position(sqoff_dt, nifty_close, end_px, "squareoff_end")

    charges = sum(1 for t in trades if t.side == "BUY") * 2 * 7.25

    return {
        "date":         ds,
        "expiry":       exp,
        "nifty_open":   nifty_open,
        "nifty_close":  nifty_close,
        "nifty_chg":    nifty_close - nifty_open,
        "trades":       trades,
        "day_pnl":      day_pnl,
        "charges":      charges,
        "realized":     day_pnl - charges,
        "done_reason":  stop_reason,
        "nifty_bars":   len(nifty_bars),
    }

# ── Output helpers ────────────────────────────────────────────────────────────
W = 130

def print_day(r):
    print(f"\n{'='*W}")
    sign = "+" if r["nifty_chg"] >= 0 else ""
    stop = f"  [DAY STOP: {r['done_reason']}]" if r["done_reason"] else ""
    print(f"  {r['date']}  |  NIFTY {r['nifty_open']:.2f} -> {r['nifty_close']:.2f} "
          f"({sign}{r['nifty_chg']:.2f})  |  Expiry: {r['expiry']}  "
          f"|  Bars: {r['nifty_bars']}{stop}")
    print(f"{'='*W}")
    print(f"  {'#':>3}  {'Side':<4}  {'Type':<2} {'Strike':>7}  {'Time':>5}  "
          f"{'Qty':>5}  {'Price':>7}  {'NIFTY':>9}  "
          f"{'CumLots':>7}  {'AvgEntry':>9}  {'LegPNL':>10}  {'DayPNL':>10}  Note")
    print(f"  {'-'*3}  {'-'*4}  {'-'*2} {'-'*7}  {'-'*5}  "
          f"{'-'*5}  {'-'*7}  {'-'*9}  "
          f"{'-'*7}  {'-'*9}  {'-'*10}  {'-'*10}  ----")

    for i, t in enumerate(r["trades"], 1):
        leg_s = f"{t.leg_pnl:>+10.2f}" if t.leg_pnl is not None else f"{'':>10}"
        day_s = f"{t.day_pnl:>+10.2f}"
        avg_s = f"{t.avg_entry:>9.2f}"
        print(f"  {i:>3}  {t.side:<4}  {t.opt_type:<2} {t.strike:>7}  "
              f"{t.bar_time.strftime('%H:%M'):>5}  "
              f"{t.qty:>5}  {t.price:>7.2f}  {t.nifty:>9.2f}  "
              f"{t.cum_lots:>7}L  {avg_s}  {leg_s}  {day_s}  {t.note}")

    print(f"  {'-'*(W-2)}")
    print(f"  Net premium: {r['day_pnl']:>+10.2f}   "
          f"Charges: -{r['charges']:.2f}   "
          f"Realized: {r['realized']:>+10.2f}")

# ── Main ──────────────────────────────────────────────────────────────────────
end_date = date.fromisoformat(args.start) if args.start else date(2026, 6, 8)
days     = biz_days(end_date, args.days)

print(f"\n{'*'*W}")
print(f"  SuperTrend(3,1) NIFTY | {args.days} business days ending {end_date} "
      f"| Leg stop=1000/lot | Day stop={DAY_STOP_LOSS:,.0f}")
print(f"{'*'*W}")

results = []
for d in days:
    print(f"\n  Processing {d} ...", end=" ", flush=True)
    r = simulate_day(d)
    if r is None:
        print("SKIPPED (no data)")
        continue
    print(f"OK  ({len(r['trades'])} trades)")
    print_day(r)
    results.append(r)

# ── Final summary ──────────────────────────────────────────────────────────────
print(f"\n\n{'*'*W}")
print(f"  FINAL SUMMARY  ({len(results)} days with data)")
print(f"{'*'*W}")
print(f"  {'Date':<12}  {'NIFTY Open':>10}  {'NIFTY Close':>11}  {'Chg':>7}  "
      f"{'Trades':>6}  {'Net Prem':>11}  {'Charges':>8}  {'Realized':>11}  Status")
print(f"  {'-'*12}  {'-'*10}  {'-'*11}  {'-'*7}  "
      f"{'-'*6}  {'-'*11}  {'-'*8}  {'-'*11}  ------")

gp = gl = 0.0
pd_ = ld = 0
for r in results:
    s = "P" if r["realized"] >= 0 else "L"
    st = f"[{s}]" + (f" STOPPED" if r["done_reason"] else "")
    if r["realized"] >= 0: gp += r["realized"]; pd_ += 1
    else:                   gl += r["realized"]; ld  += 1
    print(f"  {r['date']:<12}  {r['nifty_open']:>10.2f}  {r['nifty_close']:>11.2f}  "
          f"{r['nifty_chg']:>+7.2f}  {len(r['trades']):>6}  "
          f"{r['day_pnl']:>+11.2f}  {r['charges']:>8.2f}  "
          f"{r['realized']:>+11.2f}  {st}")

tot_pnl  = sum(r["realized"] for r in results)
tot_chg  = sum(r["charges"]  for r in results)
tot_raw  = sum(r["day_pnl"]  for r in results)
tot_trades = sum(len(r["trades"]) for r in results)

print(f"  {'-'*12}  {'-'*10}  {'-'*11}  {'-'*7}  "
      f"{'-'*6}  {'-'*11}  {'-'*8}  {'-'*11}  ------")
print(f"  {'TOTAL':<12}  {'':>10}  {'':>11}  {'':>7}  "
      f"{tot_trades:>6}  {tot_raw:>+11.2f}  {tot_chg:>8.2f}  "
      f"{tot_pnl:>+11.2f}")
print()
n = len(results)
if n:
    win_rate = pd_ / n * 100
    print(f"  Profit days: {pd_}   Loss days: {ld}   Win rate: {win_rate:.0f}%")
    print(f"  Avg daily realized: {tot_pnl/n:>+.2f}")
    print(f"  Gross profit: {gp:>+.2f}   Gross loss: {gl:>+.2f}   "
          f"Profit factor: {abs(gp/gl):.2f}" if gl else "  (no loss days)")
print(f"{'*'*W}\n")

pg.close()
