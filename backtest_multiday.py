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
ap.add_argument("--native5m", action="store_true", default=False,
                help="Force native 5m bars (skip 1m resample); used for resample parity check")
args = ap.parse_args()

# ── Strategy constants ────────────────────────────────────────────────────────
LOT          = 65
START_LOTS   = 2
ADD_LOTS     = 1
MAX_LOTS     = 5
STRIKE_STEP  = 50
OTM_STEPS    = 1
NIFTY_EXPIRY_WEEKDAY = 1   # Tuesday
_EXP_CE_SID  = -1          # synthetic sid for expired CE fallback
_EXP_PE_SID  = -2          # synthetic sid for expired PE fallback
START_H, START_M  = 9,  30
SQOFF_H, SQOFF_M  = 15, 10
LEG_STOP_PER_LOT = 1_000.0  # close if MTM loss >= this × current lots
DAY_STOP_LOSS    = 10_000.0  # no more trades if realized day loss >= this
IST = timedelta(hours=5, minutes=30)
TF_MIN = 5   # signal timeframe in minutes; source bars are fetched at 1m and resampled

# ── Imports ───────────────────────────────────────────────────────────────────
from pathlib import Path
from pymongo import MongoClient
import psycopg
from dhanhq import DhanContext, dhanhq
from pdp.indicators.supertrend import SuperTrendTracker
from pdp.instruments.snapshots import load_master_for_date
from pdp.backtest.resample import (
    resample_data_dict, resample_mongo_bars, resample_ohlcv,
)

_MASTERS_DIR = Path(os.environ.get("MASTERS_DIR", "data/masters"))

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
_inst:  dict[tuple, dict] = {}
_bars:  dict[tuple, list] = {}
_snap:  dict[date, list | None] = {}

def _snapshot_nifty(trade_date: date | None):
    """NIFTY rows from the date's instrument snapshot (latest ≤ trade_date), or None.

    Lets the backtest resolve the expiry/strike/security_id that were active on a
    historical date instead of relying on the live (currently-active) instruments table.
    """
    if trade_date is None:
        return None
    if trade_date in _snap:
        return _snap[trade_date]
    try:
        rows = load_master_for_date(trade_date, _MASTERS_DIR)
    except FileNotFoundError:
        _snap[trade_date] = None
        return None
    nifty = [r for r in rows if (r.get("underlying") or "").upper() == "NIFTY"]
    _snap[trade_date] = nifty or None
    return _snap[trade_date]

def inst_map(expiry_str, trade_date: date | None = None):
    key = (expiry_str, trade_date)
    if key in _inst:
        return _inst[key]
    # Snapshot-first: build the (strike, option_type) -> security_id map as of the date.
    snap = _snapshot_nifty(trade_date)
    if snap:
        m = {}
        for r in snap:
            if r.get("expiry") != expiry_str:
                continue
            ot = (r.get("option_type") or "").upper()
            stk = r.get("strike") or ""
            if ot not in ("CE", "PE") or stk == "":
                continue
            try:
                m[(int(float(stk)), ot)] = int(r["security_id"])
            except (ValueError, TypeError):
                continue
        if m:
            _inst[key] = m
            return m
    # Fallback: the live instruments table.
    cur = pg.execute("SELECT security_id,strike,option_type FROM instruments "
                     "WHERE underlying='NIFTY' AND expiry=%s", (expiry_str,))
    _inst[key] = {(int(r[1]), r[2]): int(r[0]) for r in cur.fetchall()}
    return _inst[key]

def active_expiry(d: date):
    # Snapshot-first: nearest expiry >= d among the date's NIFTY contracts.
    snap = _snapshot_nifty(d)
    if snap:
        exps = sorted({r["expiry"] for r in snap
                       if r.get("expiry") and r["expiry"] >= d.isoformat()})
        if exps:
            return exps[0]
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
                                      to_date=date_str, interval=1)
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
    # Source 1-minute bars and resample to the signal timeframe (matches live aggregation).
    _bars[k] = resample_ohlcv(_parse_dhan_bars(data), TF_MIN)
    return _bars[k]

def fetch_nifty(date_str):
    return fetch_bars("13", date_str, "IDX_I", "INDEX")

def fetch_opt(sid, date_str):
    return fetch_bars(sid, date_str, "NSE_FNO", "OPTIDX")

def next_weekly_expiry(d: date) -> date:
    days_ahead = (NIFTY_EXPIRY_WEEKDAY - d.weekday()) % 7
    return d + timedelta(days=days_ahead)

def expiry_available(expiry_str: str, trade_date: date | None = None) -> bool:
    """True if the expiry's contracts are resolvable — snapshot first, then live table."""
    snap = _snapshot_nifty(trade_date)
    if snap and any(r.get("expiry") == expiry_str for r in snap):
        return True
    cur = pg.execute("SELECT 1 FROM instruments WHERE underlying='NIFTY' AND expiry=%s LIMIT 1",
                     (expiry_str,))
    return cur.fetchone() is not None

def _expired_meta(opt_type: str) -> dict:
    strike_label = f"ATM+{OTM_STEPS}" if opt_type == "CE" else f"ATM-{OTM_STEPS}"
    return {
        "underlying":   "NIFTY",
        "expiry_flag":  "WEEK",
        "expiry_code":  1,
        "strike_label": strike_label,
        "option_type":  opt_type,
        "timeframe":    "5m",
    }

def _expired_from_mongo(opt_type: str, trade_ds: str) -> list:
    """Read warehoused expired-option bars for trade_ds from MongoDB (IST-naive tuples)."""
    d  = date.fromisoformat(trade_ds)
    lo = datetime(d.year, d.month, d.day, 0, 0,  tzinfo=timezone.utc)
    hi = datetime(d.year, d.month, d.day, 23, 59, tzinfo=timezone.utc)
    meta = _expired_meta(opt_type)
    q = {f"metadata.{k}": v for k, v in meta.items()}
    q["ts"] = {"$gte": lo, "$lte": hi}
    docs = list(mdb["expired_option_bars"].find(q).sort("ts", 1))
    out = []
    for doc in docs:
        ts = doc["ts"]
        if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        ist_dt = (ts + IST).replace(tzinfo=None)
        out.append((ist_dt, float(doc["open"]), float(doc["high"]),
                    float(doc["low"]), float(doc["close"])))
    return sorted(out)

def fetch_opt_expired(opt_type: str, trade_ds: str) -> list:
    """Expired weekly ATM±OTM_STEPS bars: MongoDB warehouse first, Dhan API fallback.

    On a cache miss the live API (expiry_code=1) is queried and the bars are
    persisted into `expired_option_bars` so subsequent runs read from Mongo.
    """
    sid = _EXP_CE_SID if opt_type == "CE" else _EXP_PE_SID
    k   = (sid, trade_ds)
    if k in _bars: return _bars[k]

    # 1) MongoDB warehouse
    mongo_bars = _expired_from_mongo(opt_type, trade_ds)
    if mongo_bars:
        _bars[k] = mongo_bars
        return _bars[k]

    # 2) Live API fallback (expiry_code=1 = nearest expiry from the from_date)
    drv        = "CALL" if opt_type == "CE" else "PUT"
    strike_str = f"ATM+{OTM_STEPS}" if opt_type == "CE" else f"ATM-{OTM_STEPS}"
    try:
        r = dhan.expired_options_data(
            security_id=13,
            exchange_segment="NSE_FNO",
            instrument_type="OPTIDX",
            expiry_flag="WEEK",
            expiry_code=1,
            strike=strike_str,
            drv_option_type=drv,
            required_data=["open", "high", "low", "close", "volume", "oi", "iv"],
            from_date=trade_ds,
            to_date=trade_ds,
            interval=1,
        )
        time.sleep(0.4)
    except Exception:
        _bars[k] = []; return []
    if not (isinstance(r, dict) and r.get("status") == "success"):
        _bars[k] = []; return []
    data_key = "ce" if opt_type == "CE" else "pe"
    data = r.get("data", {})
    while (isinstance(data, dict) and "data" in data
           and "ce" not in data and "pe" not in data and "open" not in data):
        data = data["data"]
    if isinstance(data, dict) and data_key in data:
        data = data[data_key]
    if isinstance(data, dict) and "data" in data and "open" not in data:
        data = data["data"]
    if not (isinstance(data, dict) and "open" in data):
        _bars[k] = []; return []
    # Source 1-minute bars and resample to the signal timeframe; persist the resampled
    # bars so the warehouse stays at the signal timeframe.
    data = resample_data_dict(data, TF_MIN)
    _bars[k] = _parse_dhan_bars(data)
    _persist_expired(opt_type, data)
    return _bars[k]

def _persist_expired(opt_type: str, data: dict) -> None:
    """Write API-fetched expired bars into the Mongo warehouse (UTC ts, idempotent)."""
    meta  = _expired_meta(opt_type)
    opens = data["open"]; highs = data["high"]; lows = data["low"]; closes = data["close"]
    vols  = data.get("volume", []); ois = data.get("oi", []); ivs = data.get("iv", [])
    tss   = data.get("timestamp", data.get("start_Time", []))
    docs  = []
    for i in range(len(closes)):
        if not closes[i] or i >= len(tss): continue
        ts = tss[i]
        if isinstance(ts, (int, float)):
            bar_ts = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            try:
                bar_ts = datetime.fromisoformat(str(ts))
                bar_ts = bar_ts.replace(tzinfo=timezone.utc) if bar_ts.tzinfo is None \
                         else bar_ts.astimezone(timezone.utc)
            except ValueError:
                continue
        docs.append({
            "ts": bar_ts, "metadata": dict(meta),
            "open": float(opens[i]), "high": float(highs[i]),
            "low": float(lows[i]), "close": float(closes[i]),
            "volume": int(vols[i]) if i < len(vols) and vols[i] is not None else 0,
            "oi":     int(ois[i])  if i < len(ois)  and ois[i]  is not None else 0,
            "iv":     float(ivs[i]) if i < len(ivs) and ivs[i] is not None else 0.0,
        })
    if not docs: return
    # Only write into an existing time-series collection; never auto-create a
    # plain collection here (the app/backfill own time-series creation).
    if "expired_option_bars" not in mdb.list_collection_names(): return
    q = {f"metadata.{key}": v for key, v in meta.items()}
    q["ts"] = {"$gte": docs[0]["ts"], "$lte": docs[-1]["ts"]}
    have = {(d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=timezone.utc))
            for d in mdb["expired_option_bars"].find(q, {"ts": 1, "_id": 0})}
    fresh = [d for d in docs if d["ts"] not in have]
    if fresh:
        try:
            mdb["expired_option_bars"].insert_many(fresh, ordered=False)
        except Exception:
            pass

# ── Position tracker ──────────────────────────────────────────────────────────
@dataclass
class Position:
    opt_type:   str
    strike:     int
    sid:        int
    total_qty:  int      = 0
    total_cost: float    = 0.0
    lots:       int      = 0
    entry_ist:  datetime | None = None

    def add(self, qty, px):
        self.total_qty  += qty
        self.total_cost += px * qty
        self.lots        = self.total_qty // LOT

    @property
    def avg_entry(self): return self.total_cost / self.total_qty if self.total_qty else 0.0

    def mtm(self, current_px): return (self.avg_entry - current_px) * self.total_qty

# ── Per-leg summary record ────────────────────────────────────────────────────
@dataclass
class LegRecord:
    opt_type:  str
    strike:    int
    entry_ist: datetime
    exit_ist:  datetime
    lots:      int
    avg_entry: float
    exit_px:   float
    leg_pnl:   float
    reason:    str

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

    # NIFTY bars — prefer 1m from Mongo and resample to the signal timeframe (matches
    # the live aggregator); fall back to native 5m, then to the Dhan API (1m + resample).
    # --native5m skips the 1m path to allow parity comparison against native 5m data.
    raw1 = [] if args.native5m else list(mdb["market_bars"].find(
        {"metadata.security_id": "13", "metadata.timeframe": "1m",
         "ts": {"$gte": st_ut, "$lte": en_ut}}).sort("ts", 1))
    if raw1:
        nifty_bars = resample_mongo_bars(raw1, TF_MIN)
    else:
        raw5 = list(mdb["market_bars"].find(
            {"metadata.security_id": "13", "metadata.timeframe": "5m",
             "ts": {"$gte": st_ut, "$lte": en_ut}}).sort("ts", 1))
        seen, nifty_bars = set(), []
        for b in raw5:
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

    correct_exp  = next_weekly_expiry(trade_date).isoformat()
    use_expired  = not expiry_available(correct_exp, trade_date)
    if use_expired:
        exp  = correct_exp
        imap = {}
    else:
        exp  = active_expiry(trade_date)
        if not exp: return None
        imap = inst_map(exp, trade_date)

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

    # Pre-fetch option bars
    if use_expired:
        fetch_opt_expired("CE", ds)
        fetch_opt_expired("PE", ds)
    else:
        for sid in set(imap.values()):
            fetch_opt(sid, ds)

    # ── Bar-by-bar simulation ──────────────────────────────────────────────────
    pos:         Position | None  = None
    trades:      list[Trade]      = []
    leg_records: list[LegRecord]  = []
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
        if pos.entry_ist is not None:
            leg_records.append(LegRecord(
                opt_type=pos.opt_type,
                strike=pos.strike,
                entry_ist=pos.entry_ist,
                exit_ist=ist_dt,
                lots=pos.lots,
                avg_entry=pos.avg_entry,
                exit_px=close_px,
                leg_pnl=leg_pnl,
                reason=reason,
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
        if use_expired:
            sid = _EXP_CE_SID if desired == "CE" else _EXP_PE_SID
        else:
            sid = imap.get(k)
            if not sid: continue

        opt_bars_n = _bars.get((sid, ds), [])

        if pos is None:
            # New entry
            entry_px = price_at(opt_bars_n, ist_dt, prefer="open")
            if entry_px:
                pos = Position(opt_type=desired, strike=k[0], sid=sid, entry_ist=ist_dt)
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
        "leg_records":  leg_records,
        "day_pnl":      day_pnl,
        "charges":      charges,
        "realized":     day_pnl - charges,
        "done_reason":  stop_reason,
        "nifty_bars":   len(nifty_bars),
        "use_expired":  use_expired,
    }

# ── Output helpers ────────────────────────────────────────────────────────────
W = 130

def print_day(r):
    print(f"\n{'='*W}")
    sign = "+" if r["nifty_chg"] >= 0 else ""
    stop    = f"  [DAY STOP: {r['done_reason']}]" if r["done_reason"] else ""
    approx  = "  [APPROX: expired_options_data]" if r.get("use_expired") else ""
    print(f"  {r['date']}  |  NIFTY {r['nifty_open']:.2f} -> {r['nifty_close']:.2f} "
          f"({sign}{r['nifty_chg']:.2f})  |  Expiry: {r['expiry']}  "
          f"|  Bars: {r['nifty_bars']}{stop}{approx}")
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

    leg_records: list[LegRecord] = r.get("leg_records", [])
    if leg_records:
        LW = 90
        print()
        print(f"  LEG SUMMARY")
        print(f"  {'#':>3}  {'Type':<2} {'Strike':>7}  {'Entry':>5}  {'Exit':>5}  "
              f"{'Lots':>4}  {'AvgEntry':>9}  {'Exit Rs':>8}  {'Leg P&L':>10}  Reason")
        print(f"  {'-'*3}  {'-'*2} {'-'*7}  {'-'*5}  {'-'*5}  "
              f"{'-'*4}  {'-'*9}  {'-'*8}  {'-'*10}  ------")
        wins = losses = 0
        for i, lr in enumerate(leg_records, 1):
            pnl_s = f"{lr.leg_pnl:>+10.2f}"
            print(f"  {i:>3}  {lr.opt_type:<2} {lr.strike:>7}  "
                  f"{lr.entry_ist.strftime('%H:%M'):>5}  "
                  f"{lr.exit_ist.strftime('%H:%M'):>5}  "
                  f"{lr.lots:>4}L  {lr.avg_entry:>9.2f}  "
                  f"{lr.exit_px:>8.2f}  {pnl_s}  {lr.reason}")
            if lr.leg_pnl >= 0:
                wins += 1
            else:
                losses += 1
        total_leg_pnl = sum(lr.leg_pnl for lr in leg_records)
        print(f"  {'-'*LW}")
        print(f"  {len(leg_records)} leg(s)  |  Total P&L: {total_leg_pnl:>+.2f}  |  "
              f"Win: {wins}  Loss: {losses}")

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
