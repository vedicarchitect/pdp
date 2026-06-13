"""
Multi-day backtest: SuperTrend(3,1) NIFTY option-selling with risk management.

Risk rules:
  - LEG STOP  : if current open position MTM loss >= 5,000  -> close at bar close price
  - DAY STOP  : if cumulative realized day loss >= 10,000   -> flat + no more trades today

Option pricing:
  - Reads from the unified ``option_bars`` warehouse keyed by the real fixed contract
    (underlying, expiry_date, strike, option_type, timeframe).  The old
    ``expired_option_bars`` ATM-label path has been retired.
  - Target strike is derived from spot (ATM rounded to STRIKE_STEP grid + OTM offset).
  - Expiry date is resolved from the NIFTY expiry calendar (WEEK, code=1).
  - Nearest-strike fallback within ±WAREHOUSE_STRIKE_BAND × STRIKE_STEP when the exact
    target has no bars for the day.
  - A held position is priced as one stable fixed contract across all days it is held
    (no strike drift).

Usage:
  python backtest_multiday.py              # last 7 business days
  python backtest_multiday.py --days 14
  python backtest_multiday.py --days 3 --start 2026-06-01
"""
import sys, os, time, argparse, logging
sys.path.insert(0, "src")
from dotenv import load_dotenv; load_dotenv()

from datetime import datetime, date, timedelta, timezone
from dataclasses import dataclass

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
START_H, START_M  = 9,  30
SQOFF_H, SQOFF_M  = 15, 10
LEG_STOP_PER_LOT = 1_000.0  # close if MTM loss >= this × current lots
DAY_STOP_LOSS    = 10_000.0  # no more trades if realized day loss >= this
IST = timedelta(hours=5, minutes=30)
TF_MIN = 5   # signal timeframe in minutes; source bars are fetched at 1m and resampled

# ── Logging (script-level; matches backtest's use of stdlib logging) ──────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backtest")

# ── Imports ───────────────────────────────────────────────────────────────────
from pathlib import Path
from pymongo import MongoClient
import psycopg
from dhanhq import DhanContext, dhanhq
from pdp.indicators.supertrend import SuperTrendTracker
from pdp.instruments.snapshots import load_master_for_date
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar
from pdp.backtest.resample import (
    resample_mongo_bars, resample_ohlcv,
)
from pdp.settings import get_settings

_MASTERS_DIR = Path(os.environ.get("MASTERS_DIR", "data/masters"))

mdb = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017"))[
    os.environ.get("MONGO_DB_NAME", "pdp")]

pg_url = (os.environ["DATABASE_URL"]
          .replace("postgresql+asyncpg://", "postgresql://")
          .replace("postgresql+psycopg://",  "postgresql://"))
pg = psycopg.connect(pg_url)

dhan = dhanhq(DhanContext(os.environ["DHAN_CLIENT_ID"],
                           os.environ["DHAN_ACCESS_TOKEN"]))

# ── Expiry calendar (load once; reads data/expiry/nifty_expiries.json) ────────
_settings = get_settings()
try:
    _cal = NiftyExpiryCalendar.load(_settings.EXPIRY_CACHE_PATH)
    log.info("Expiry calendar loaded from %s", _settings.EXPIRY_CACHE_PATH)
except Exception as _cal_err:
    _cal = None
    log.warning("Expiry calendar unavailable (%s); will fall back to next_weekly_expiry()", _cal_err)

# Warehouse band for nearest-strike fallback (from settings, default 10 steps).
_WAREHOUSE_STRIKE_BAND = _settings.WAREHOUSE_STRIKE_BAND
_WAREHOUSE_STRIKE_STEP = _settings.WAREHOUSE_STRIKE_STEP

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

def _dhan_nifty_fallback(date_str):
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

# ── Expiry resolution via the empirical calendar ──────────────────────────────

def _resolve_expiry_from_calendar(trade_date: date) -> date | None:
    """Use the expiry calendar to find the nearest WEEK code=1 expiry on or after trade_date."""
    if _cal is None:
        return None
    return _cal.resolve_expiry(trade_date, "WEEK", 1)

# ── Fixed-strike option_bars reader ──────────────────────────────────────────

def _option_bars_cache_key(expiry_date: date, strike: float, opt_type: str, trade_date: date) -> tuple:
    """Unique cache key for a fixed-contract day's bars."""
    return ("option_bars", expiry_date.isoformat(), float(strike), opt_type.upper(), trade_date.isoformat())

def _fetch_option_bars_for_day(
    trade_date: date,
    opt_type: str,
    target_strike: float,
    expiry_date: date,
) -> list:
    """Read bars for (expiry_date, strike, opt_type) on trade_date from option_bars.

    Returns IST-naive (dt, o, h, lo, c) tuples resampled to TF_MIN, or [] if none found.
    This is the primary reader; no fallback — call _fetch_opt_fixed() for fallback logic.
    """
    expiry_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day, tzinfo=timezone.utc)
    # Trade day in UTC: IST 00:00 = UTC 18:30 prev day; IST 23:59 = UTC 18:29 same day.
    # Use a wide UTC window covering the full IST trade day.
    lo_utc = datetime(trade_date.year, trade_date.month, trade_date.day, 0, 0, tzinfo=timezone.utc)
    hi_utc = datetime(trade_date.year, trade_date.month, trade_date.day, 23, 59, tzinfo=timezone.utc)

    docs = list(mdb["option_bars"].find({
        "underlying": "NIFTY",
        "expiry_date": expiry_dt,
        "strike": float(target_strike),
        "option_type": opt_type.upper(),
        "timeframe": "1m",
        "ts": {"$gte": lo_utc, "$lte": hi_utc},
    }).sort("ts", 1))

    if not docs:
        return []

    # Convert UTC ts -> IST-naive tuples for resample_ohlcv.
    raw = []
    for doc in docs:
        ts = doc["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ist_dt = (ts + IST).replace(tzinfo=None)
        raw.append((ist_dt, float(doc["open"]), float(doc["high"]),
                    float(doc["low"]), float(doc["close"])))

    return resample_ohlcv(sorted(raw), TF_MIN)


def _nearest_strike_fallback(
    trade_date: date,
    opt_type: str,
    target_strike: float,
    expiry_date: date,
) -> tuple[float | None, list]:
    """Search outward ±WAREHOUSE_STRIKE_BAND steps from target_strike for a strike with bars.

    Returns (actual_strike_used, bars) or (None, []) if nothing found in band.
    """
    expiry_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day, tzinfo=timezone.utc)
    lo_utc = datetime(trade_date.year, trade_date.month, trade_date.day, 0, 0, tzinfo=timezone.utc)
    hi_utc = datetime(trade_date.year, trade_date.month, trade_date.day, 23, 59, tzinfo=timezone.utc)

    # Build list of candidate strikes in outward order from target.
    candidates = []
    for step in range(1, _WAREHOUSE_STRIKE_BAND + 1):
        candidates.append(target_strike + step * _WAREHOUSE_STRIKE_STEP)
        candidates.append(target_strike - step * _WAREHOUSE_STRIKE_STEP)

    for candidate in candidates:
        docs = list(mdb["option_bars"].find({
            "underlying": "NIFTY",
            "expiry_date": expiry_dt,
            "strike": float(candidate),
            "option_type": opt_type.upper(),
            "timeframe": "1m",
            "ts": {"$gte": lo_utc, "$lte": hi_utc},
        }).sort("ts", 1).limit(1))
        if docs:
            # Found bars at this candidate — fetch full day.
            bars = _fetch_option_bars_for_day(trade_date, opt_type, candidate, expiry_date)
            if bars:
                return float(candidate), bars

    return None, []


def fetch_opt_fixed(
    trade_date: date,
    opt_type: str,
    target_strike: float,
    expiry_date: date,
) -> tuple[float, list]:
    """Fetch bars for a fixed-strike contract from the option_bars warehouse.

    Flow:
      1. Exact strike from option_bars (1m → resample TF_MIN).
      2. Nearest available strike within ±WAREHOUSE_STRIKE_BAND if exact is missing (log substitution).
      3. Live Dhan API fallback if warehouse has nothing (persists into option_bars for next run).

    Returns (actual_strike_used, bars).  bars=[] if all paths fail.
    """
    cache_key = _option_bars_cache_key(expiry_date, target_strike, opt_type, trade_date)
    if cache_key in _bars:
        cached = _bars[cache_key]
        # cache stores (actual_strike, bars)
        return cached

    # 1) Exact strike from warehouse.
    bars = _fetch_option_bars_for_day(trade_date, opt_type, target_strike, expiry_date)
    if bars:
        log.debug("opt_bars_exact strike=%.0f %s expiry=%s date=%s bars=%d",
                  target_strike, opt_type, expiry_date, trade_date, len(bars))
        result = (target_strike, bars)
        _bars[cache_key] = result
        return result

    # 2) Nearest-strike fallback within band.
    fallback_strike, fallback_bars = _nearest_strike_fallback(
        trade_date, opt_type, target_strike, expiry_date
    )
    if fallback_bars:
        log.warning(
            "opt_bars_nearest_strike_fallback  date=%s %s expiry=%s  "
            "target=%.0f -> used=%.0f  bars=%d",
            trade_date, opt_type, expiry_date,
            target_strike, fallback_strike, len(fallback_bars),
        )
        result = (fallback_strike, fallback_bars)
        _bars[cache_key] = result
        return result

    # 3) Live Dhan API fallback (requires live creds + expiry resolvable by Dhan).
    log.warning("opt_bars_no_warehouse_data date=%s %s expiry=%s strike=%.0f -- trying Dhan API",
                trade_date, opt_type, expiry_date, target_strike)
    imap = inst_map(expiry_date.isoformat(), trade_date)
    k_live = (int(target_strike), opt_type.upper())
    sid = imap.get(k_live)
    if sid:
        ds = trade_date.isoformat()
        live_bars = fetch_opt(sid, ds)
        if live_bars:
            _persist_to_option_bars(opt_type, target_strike, expiry_date, live_bars)
            result = (target_strike, live_bars)
            _bars[cache_key] = result
            return result

    result = (target_strike, [])
    _bars[cache_key] = result
    return result


def _persist_to_option_bars(
    opt_type: str,
    strike: float,
    expiry_date: date,
    bars: list,      # IST-naive (dt, o, h, lo, c) tuples (already resampled to TF_MIN)
) -> None:
    """Upsert bars fetched from the live API into option_bars (idempotent, first-write-wins).

    Bars from the live API arrive as IST-naive tuples; we convert them back to UTC for
    storage.  Timeframe is stored as the signal TF_MIN string (e.g. "5m") since that is
    what was persisted — the warehouse also holds 1m bars from backfill, but the API
    path always produces TF_MIN-resampled bars.
    """
    if not bars:
        return
    expiry_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day, tzinfo=timezone.utc)
    tf_label = f"{TF_MIN}m"
    docs = []
    for (ist_dt, o, h, lo, c) in bars:
        if not isinstance(ist_dt, datetime):
            log.warning("opt_bars_persist_bad_ts: expected datetime, got %s — skipping bar", type(ist_dt))
            continue
        # ist_dt is naive IST; convert to UTC aware.
        utc_ts = (ist_dt - IST).replace(tzinfo=timezone.utc)
        docs.append({
            "underlying": "NIFTY",
            "expiry_date": expiry_dt,
            "strike": float(strike),
            "option_type": opt_type.upper(),
            "timeframe": tf_label,
            "ts": utc_ts,
            "open": float(o), "high": float(h), "low": float(lo), "close": float(c),
            "volume": 0, "oi": 0, "iv": 0.0,
            "expiry_flag": "WEEK",
            "trading_symbol": "",
            "security_id": None,
            "strike_label": None,
            "source": "dhan_api",
        })
    if not docs:
        return
    from pymongo import UpdateOne
    KEY_FIELDS = ("underlying", "expiry_date", "strike", "option_type", "timeframe", "ts")
    ops = [UpdateOne({k: d[k] for k in KEY_FIELDS}, {"$setOnInsert": d}, upsert=True)
           for d in docs]
    try:
        mdb["option_bars"].bulk_write(ops, ordered=False)
    except Exception as exc:
        log.warning("opt_bars_persist_failed: %s", exc)


# ── Position tracker ──────────────────────────────────────────────────────────
@dataclass
class Position:
    opt_type:    str
    strike:      float         # actual fixed strike used (may differ from target after fallback)
    expiry_date: date          # fixed expiry for this position
    sid:         int | None    # security_id if available (for Dhan leg lookup)
    total_qty:   int      = 0
    total_cost:  float    = 0.0
    lots:        int      = 0
    entry_ist:   datetime | None = None

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
    strike:    float
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
    strike:      float
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
        dhan_bars = _dhan_nifty_fallback(ds)
        nifty_bars = [{"ts": dt.replace(tzinfo=timezone.utc) - IST,
                       "open": o, "high": h, "low": l, "close": c}
                      for dt, o, h, l, c in dhan_bars]
    if not nifty_bars: return None

    nifty_open  = float(nifty_bars[0]["open"])
    nifty_close = float(nifty_bars[-1]["close"])

    # ── Expiry resolution: calendar first, then snapshot/live table ──
    # The calendar gives the real empirically-detected expiry for the trade day.
    cal_expiry = _resolve_expiry_from_calendar(trade_date)
    if cal_expiry is not None:
        exp = cal_expiry.isoformat()
        exp_date = cal_expiry
    else:
        # Fallback: nearest expiry from snapshot / live instruments.
        correct_exp = next_weekly_expiry(trade_date).isoformat()
        exp = correct_exp
        exp_date = date.fromisoformat(exp)

    # use_expired: True when the expiry is not in the live instruments table.
    # With the fixed-strike warehouse, we can still price from option_bars even when
    # the expiry is no longer active — so this flag mainly controls the Dhan API fallback.
    use_expired = not expiry_available(exp, trade_date)
    imap = {} if use_expired else inst_map(exp, trade_date)

    # Pre-fetch option bars for the day: read the strike band for both CE and PE from
    # option_bars so that the bar-by-bar loop can call price_at quickly.
    # We pre-fetch a representative set; the bar-by-bar loop will call fetch_opt_fixed
    # which has its own cache.
    #
    # Precompute spot to get a ballpark strike for pre-warm (optional; the bar-by-bar
    # loop already caches results, so this just warms the cache once).
    _approx_spot = nifty_open
    for _ot in ("CE", "PE"):
        _tgt = float(otm_strike(_approx_spot, _ot))
        fetch_opt_fixed(trade_date, _ot, _tgt, exp_date)

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

    # ── Bar-by-bar simulation ──────────────────────────────────────────────────
    pos:         Position | None  = None
    trades:      list[Trade]      = []
    leg_records: list[LegRecord]  = []
    day_pnl    = 0.0
    done       = False
    stop_reason = ""

    def _pos_bars(p: Position) -> list:
        """Retrieve the cached bars for the current position's fixed contract."""
        k = _option_bars_cache_key(p.expiry_date, p.strike, p.opt_type, trade_date)
        cached = _bars.get(k)
        if cached is not None:
            return cached[1]  # (actual_strike, bars) tuple
        # Re-fetch (shouldn't be needed, but guard for safety).
        _, bars = fetch_opt_fixed(trade_date, p.opt_type, p.strike, p.expiry_date)
        return bars

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
                sq_bars = _pos_bars(pos)
                sq_px = price_at(sq_bars, ist_dt, prefer="open") or price_at(sq_bars, ist_dt, prefer="close")
                if sq_px:
                    close_position(ist_dt, bar_open, sq_px, "squareoff")
            break

        if done: continue

        desired = "PE" if st.direction > 0 else "CE"

        # ── Check leg stop-loss at bar CLOSE (if position open) ──
        if pos:
            pos_bars = _pos_bars(pos)
            bar_close_px = price_at(pos_bars, ist_dt, prefer="close")
            if bar_close_px:
                mtm = pos.mtm(bar_close_px)
                if mtm <= -(LEG_STOP_PER_LOT * pos.lots):
                    limit = LEG_STOP_PER_LOT * pos.lots
                    close_position(ist_dt, bar_close, bar_close_px, f"leg_stop (mtm={mtm:+.0f}, limit={-limit:.0f})")
                    continue   # no new entry on stop bar

        # ── Flip: close current, open new ──
        if pos and pos.opt_type != desired:
            flip_bars = _pos_bars(pos)
            flip_px = price_at(flip_bars, ist_dt, prefer="open")
            if flip_px:
                close_position(ist_dt, bar_open, flip_px, "flip")
            else:
                pos = None   # can't price it; clear position
            if done: continue

        # ── Compute target strike for the desired leg ──
        target_stk = float(otm_strike(bar_close, desired))

        # If we already have an open position for the same type, check if the strike
        # matches (positional: hold same contract, don't drift strikes intraday).
        if pos is not None and pos.opt_type == desired:
            # Positional path: continue pricing off the held contract, not a new target.
            new_bars = _pos_bars(pos)
            actual_strike = pos.strike
        else:
            # New or flipped leg: resolve the contract from the warehouse.
            actual_strike, new_bars = fetch_opt_fixed(trade_date, desired, target_stk, exp_date)
            if not new_bars:
                continue

        if pos is None:
            # New entry
            entry_px = price_at(new_bars, ist_dt, prefer="open")
            if entry_px:
                pos = Position(
                    opt_type=desired, strike=actual_strike, expiry_date=exp_date,
                    sid=imap.get((int(actual_strike), desired.upper())),
                    entry_ist=ist_dt,
                )
                pos.add(START_LOTS * LOT, entry_px)
                trades.append(Trade(
                    side="SELL", opt_type=desired, strike=actual_strike,
                    bar_time=ist_dt, qty=START_LOTS * LOT, price=entry_px,
                    nifty=bar_close,
                    note=f"open {START_LOTS}L",
                    cum_lots=pos.lots, avg_entry=pos.avg_entry,
                    day_pnl=day_pnl,
                ))
        elif pos.sid == imap.get((int(actual_strike), desired.upper()), pos.sid) and pos.lots < MAX_LOTS:
            # Scale in (same contract, same expiry)
            add_px = price_at(new_bars, ist_dt, prefer="open")
            if add_px:
                pos.add(ADD_LOTS * LOT, add_px)
                trades.append(Trade(
                    side="SELL", opt_type=desired, strike=actual_strike,
                    bar_time=ist_dt, qty=ADD_LOTS * LOT, price=add_px,
                    nifty=bar_close,
                    note=f"scale +{ADD_LOTS}L -> {pos.lots}L",
                    cum_lots=pos.lots, avg_entry=pos.avg_entry,
                    day_pnl=day_pnl,
                ))

    # Unclosed position at end (rare — squareoff loop should handle)
    if pos:
        end_bars = _pos_bars(pos)
        end_px = (price_at(end_bars, sqoff_dt, prefer="close") or
                  price_at(end_bars, sqoff_dt, prefer="open"))
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
        "expiry_source": "calendar" if cal_expiry else "fallback",
    }

# ── Output helpers ────────────────────────────────────────────────────────────
W = 130

def print_day(r):
    print(f"\n{'='*W}")
    sign = "+" if r["nifty_chg"] >= 0 else ""
    stop    = f"  [DAY STOP: {r['done_reason']}]" if r["done_reason"] else ""
    exp_src = f"  [expiry:{r.get('expiry_source','?')}]"
    print(f"  {r['date']}  |  NIFTY {r['nifty_open']:.2f} -> {r['nifty_close']:.2f} "
          f"({sign}{r['nifty_chg']:.2f})  |  Expiry: {r['expiry']}{exp_src}  "
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
        print(f"  {i:>3}  {t.side:<4}  {t.opt_type:<2} {t.strike:>7.0f}  "
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
            print(f"  {i:>3}  {lr.opt_type:<2} {lr.strike:>7.0f}  "
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
print(f"  Option pricing: fixed-strike option_bars warehouse (nearest-strike fallback within ±{_WAREHOUSE_STRIKE_BAND} steps)")
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
