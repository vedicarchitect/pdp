"""Read-only index expiry-day option-chain analysis + intraday OI tracker.

Covers NIFTY, BANKNIFTY and SENSEX (FINNIFTY too) in one run, each at its own nearest
expiry. Two modes:

1. Analysis (default) — live chain (OI, IV, Greeks) + India VIX → max pain, PCR, OI
   walls, ATM-straddle expected move, IV skew, ATM gamma/delta → probable close zone.

2. Tracker (--track) — snapshots OI for the ATM +/- N strikes and diffs the latest vs the
   morning baseline AND the previous snapshot. Significant shifts vs morning are emitted as
   events for later consumption (alerting / features). Pass --interval 300 to self-loop ~5 min.
   Storage (per the DB-split rule): JSONL local history is always written (it powers the
   morning/prev baseline); --store adds durable Mongo `oi_snapshots` (time-series, system of
   record) and Redis `oi:{sym}` hot value + `oi.events.{sym}` pub-sub. A down service degrades
   to JSONL-only rather than failing the run.

This script ONLY reads market data (no orders). Examples:

    uv run python scripts/expiry_analysis.py                       # analyse all 3 indices
    uv run python scripts/expiry_analysis.py --symbol NIFTY
    uv run python scripts/expiry_analysis.py --track               # one OI snapshot pass
    uv run python scripts/expiry_analysis.py --track --interval 300  # snapshot every 5 min

It is intentionally self-contained (no FastAPI app, no Redis) so it can run standalone.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pdp.settings import get_settings

IST = ZoneInfo("Asia/Kolkata")

# Where per-day OI snapshots + derived events are persisted (repo-root/data/oi_snapshots).
SNAP_DIR = Path(__file__).resolve().parents[1] / "data" / "oi_snapshots"

# Index underlyings in Dhan's IDX_I segment (security_id, segment).
UNDERLYINGS: dict[str, tuple[int, str]] = {
    "NIFTY": (13, "IDX_I"),
    "BANKNIFTY": (25, "IDX_I"),
    "FINNIFTY": (27, "IDX_I"),
    "SENSEX": (51, "IDX_I"),
}

# Nominal index step (strike spacing) used only for tidy rounding in the verdict.
STRIKE_STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "SENSEX": 100}


def _make_client():
    from dhanhq import DhanContext, dhanhq

    s = get_settings()
    return dhanhq(DhanContext(s.DHAN_CLIENT_ID, s.DHAN_ACCESS_TOKEN))


def _unwrap(resp: dict) -> dict:
    """Return the inner chain dict, tolerating Dhan's double-wrapped envelope."""
    if not isinstance(resp, dict) or resp.get("status") != "success":
        raise RuntimeError(f"Dhan call failed: {str(resp)[:300]}")
    data = resp.get("data") or {}
    if isinstance(data, dict) and "oc" not in data and isinstance(data.get("data"), dict):
        data = data["data"]
    return data


def fetch_expiries(client, sec_id: int, seg: str) -> list[str]:
    resp = client.expiry_list(sec_id, seg)
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict):
        data = data.get("data", [])
    return sorted(str(e) for e in (data or []) if e)


def fetch_chain(client, sec_id: int, seg: str, expiry: str):
    resp = client.option_chain(under_security_id=sec_id, under_exchange_segment=seg, expiry=expiry)
    data = _unwrap(resp)
    spot = float(data["last_price"])
    rows: list[dict] = []
    for k, payload in sorted((data.get("oc") or {}).items(), key=lambda kv: float(kv[0])):
        row: dict = {"strike": float(k)}
        for side in ("ce", "pe"):
            leg = payload.get(side) or {}
            g = leg.get("greeks") or {}
            row[f"{side}_ltp"] = leg.get("last_price")
            row[f"{side}_oi"] = leg.get("oi") or 0
            row[f"{side}_oi_change"] = leg.get("oi_change") or 0
            row[f"{side}_iv"] = leg.get("implied_volatility")
            row[f"{side}_delta"] = g.get("delta")
            row[f"{side}_gamma"] = g.get("gamma")
        rows.append(row)
    return spot, rows


def fetch_india_vix(client) -> float | None:
    """Resolve India VIX security id from the security master and quote it."""
    try:
        from dhanhq import dhanhq as _dh

        master = _dh.fetch_security_list("compact")
        if master is None:
            return None
        sym = master["SEM_TRADING_SYMBOL"].astype(str).str.upper()
        cust = master.get("SEM_CUSTOM_SYMBOL")
        mask = sym.str.contains("VIX", na=False)
        if cust is not None:
            mask = mask | cust.astype(str).str.upper().str.contains("INDIA VIX", na=False)
        hits = master[mask]
        if hits.empty:
            return None
        vix_id = str(hits.iloc[0]["SEM_SMST_SECURITY_ID"])
        time.sleep(1.1)  # quote API: 1 req/sec
        q = client.quote_data({"IDX_I": [int(vix_id)]})
        data = _unwrap(q) if q.get("status") == "success" else {}
        # quote_data nests by segment -> security_id -> {last_price,...}
        for seg_block in (data or {}).values():
            if isinstance(seg_block, dict):
                for leg in seg_block.values():
                    if isinstance(leg, dict) and leg.get("last_price"):
                        return float(leg["last_price"])
        return None
    except Exception as exc:  # noqa: BLE001 - VIX is best-effort, never fatal
        print(f"  (India VIX unavailable: {exc})")
        return None


# ---- analytics -------------------------------------------------------------

def max_pain(rows: list[dict]) -> float:
    strikes = [r["strike"] for r in rows]
    ce = {r["strike"]: r["ce_oi"] for r in rows}
    pe = {r["strike"]: r["pe_oi"] for r in rows}
    best_k, best_pain = strikes[0], None
    for k in strikes:
        pain = sum(max(0, s - k) * ce[s] for s in strikes) + sum(max(0, k - s) * pe[s] for s in strikes)
        if best_pain is None or pain < best_pain:
            best_pain, best_k = pain, k
    return best_k


def pcr(rows: list[dict]) -> float:
    tce = sum(r["ce_oi"] for r in rows)
    tpe = sum(r["pe_oi"] for r in rows)
    return (tpe / tce) if tce else float("nan")


def top_oi(rows: list[dict], side: str, n: int = 3) -> list[tuple[float, int, int]]:
    ranked = sorted(rows, key=lambda r: r[f"{side}_oi"], reverse=True)[:n]
    return [(r["strike"], r[f"{side}_oi"], r[f"{side}_oi_change"]) for r in ranked]


def atm_row(rows: list[dict], spot: float) -> dict:
    return min(rows, key=lambda r: abs(r["strike"] - spot))


def fmt(x, nd=2):
    return "n/a" if x is None else f"{x:,.{nd}f}"


# ---- OI snapshot tracking --------------------------------------------------

def window_strikes(rows: list[dict], spot: float, n: int) -> list[dict]:
    """Return the ATM strike plus the n nearest strikes on each side (ATM +/- n)."""
    ordered = sorted(rows, key=lambda r: r["strike"])
    atm = min(range(len(ordered)), key=lambda i: abs(ordered[i]["strike"] - spot))
    lo, hi = max(0, atm - n), min(len(ordered), atm + n + 1)
    return ordered[lo:hi]


def take_snapshot(symbol: str, expiry: str, spot: float, rows: list[dict], n: int) -> dict:
    """Build a compact, persistable snapshot of OI for the ATM +/- n strikes."""
    win = window_strikes(rows, spot, n)
    return {
        "ts": datetime.now(IST).isoformat(timespec="seconds"),
        "symbol": symbol,
        "expiry": expiry,
        "spot": spot,
        "strikes": [
            {
                "strike": r["strike"],
                "ce_oi": int(r["ce_oi"] or 0),
                "pe_oi": int(r["pe_oi"] or 0),
                "ce_ltp": r.get("ce_ltp"),
                "pe_ltp": r.get("pe_ltp"),
            }
            for r in win
        ],
    }


def _snap_paths(symbol: str, expiry: str) -> tuple[Path, Path]:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    base = f"{symbol}_{expiry}_{today}"
    return SNAP_DIR / f"{base}.snapshots.jsonl", SNAP_DIR / f"{base}.events.jsonl"


def load_snapshots(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _append_jsonl(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj) + "\n")


def _index_by_strike(snap: dict) -> dict[float, dict]:
    return {s["strike"]: s for s in snap["strikes"]}


def classify(side: str, delta: int) -> tuple[str, str]:
    """Map an OI delta to (action, market read) for a CE or PE leg."""
    if delta == 0:
        return "flat", "no change"
    writing = delta > 0
    if side == "ce":
        return ("call writing", "resistance building (bearish)") if writing else (
            "call unwinding", "resistance fading (bullish)")
    return ("put writing", "support building (bullish)") if writing else (
        "put unwinding", "support fading (bearish)")


class Sinks:
    """Optional durable/hot stores for snapshots + events, per Non-Negotiable #8.

    JSONL (handled in track_oi) is the always-on local history that powers the morning/prev
    baseline. These sinks are additive:
      - Mongo  `oi_snapshots` time-series : durable everyday warehouse (system of record).
      - Redis  `oi:{sym}` + `oi.events.{sym}` : hot latest value + live event pub-sub.
    A sink whose service is unreachable disables itself and the run continues on JSONL.
    """

    def __init__(self, targets: set[str]) -> None:
        self.mongo = None
        self.redis = None
        if "mongo" in targets:
            self._init_mongo()
        if "redis" in targets:
            self._init_redis()

    def _init_mongo(self) -> None:
        try:
            from pymongo import MongoClient

            s = get_settings()
            db = MongoClient(s.MONGO_URI, serverSelectionTimeoutMS=2000)[s.MONGO_DB_NAME]
            try:  # idempotent create; mirrors pdp.mongo.collections._ensure_oi_snapshots
                db.create_collection(
                    "oi_snapshots",
                    timeseries={"timeField": "ts", "metaField": "metadata", "granularity": "minutes"},
                )
            except Exception:  # noqa: BLE001 - already exists
                pass
            self.mongo = db["oi_snapshots"]
        except Exception as exc:  # noqa: BLE001
            print(f"  (mongo sink disabled: {exc})")

    def _init_redis(self) -> None:
        try:
            import redis

            self.redis = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
            self.redis.ping()
        except Exception as exc:  # noqa: BLE001
            print(f"  (redis sink disabled: {exc})")
            self.redis = None

    def write(self, snap: dict, events: list[dict]) -> None:
        if self.mongo is not None:
            try:
                ts = datetime.fromisoformat(snap["ts"])
                self.mongo.insert_one({
                    "ts": ts,
                    "metadata": {"symbol": snap["symbol"], "expiry": snap["expiry"]},
                    "spot": snap["spot"],
                    "strikes": snap["strikes"],
                    "events": events,
                })
            except Exception as exc:  # noqa: BLE001 - never break the tracker on a store error
                print(f"  (mongo write failed: {exc})")
        if self.redis is not None:
            try:
                sym = snap["symbol"]
                self.redis.set(f"oi:{sym}", json.dumps(snap), ex=86400)  # hot latest value
                for e in events:
                    payload = json.dumps(e)
                    self.redis.publish(f"oi.events.{sym}", payload)  # live fan-out
                    self.redis.lpush(f"oi:events:{sym}", payload)     # recent-events buffer
                if events:
                    self.redis.ltrim(f"oi:events:{sym}", 0, 199)
                    self.redis.expire(f"oi:events:{sym}", 86400)
            except Exception as exc:  # noqa: BLE001
                print(f"  (redis write failed: {exc})")


def track_oi(symbol: str, expiry: str, spot: float, rows: list[dict], n: int,
             thr_pct: float, thr_abs: int, sinks: Sinks | None = None) -> None:
    """Append a snapshot, diff vs morning baseline + previous, print a table, emit events."""
    snap_path, ev_path = _snap_paths(symbol, expiry)
    history = load_snapshots(snap_path)
    snap = take_snapshot(symbol, expiry, spot, rows, n)
    _append_jsonl(snap_path, snap)

    baseline = history[0] if history else snap   # morning (first) snapshot of the day
    prev = history[-1] if history else snap       # most recent prior snapshot
    base_ix, prev_ix = _index_by_strike(baseline), _index_by_strike(prev)
    seq = len(history) + 1

    print(f"\n=== {symbol} OI tracker  snapshot #{seq}  @ {snap['ts']}  spot {fmt(spot,0)} ===")
    if history:
        print(f"baseline {baseline['ts']} (spot {fmt(baseline['spot'],0)})  |  prev {prev['ts']}  |  ATM +/- {n} strikes")
    else:
        print(f"first snapshot today -> this becomes the morning baseline  |  ATM +/- {n} strikes")
    print(f"{'strike':>8} | {'CE_OI':>11} {'dCE_morn':>11} {'dCE_prev':>10} | "
          f"{'PE_OI':>11} {'dPE_morn':>11} {'dPE_prev':>10} | read")

    events: list[dict] = []
    for s in snap["strikes"]:
        k = s["strike"]
        b, p = base_ix.get(k), prev_ix.get(k)
        dce_m = s["ce_oi"] - (b["ce_oi"] if b else s["ce_oi"])
        dpe_m = s["pe_oi"] - (b["pe_oi"] if b else s["pe_oi"])
        dce_p = s["ce_oi"] - (p["ce_oi"] if p else s["ce_oi"])
        dpe_p = s["pe_oi"] - (p["pe_oi"] if p else s["pe_oi"])

        # dominant read for the row = whichever side moved more vs morning
        side = "pe" if abs(dpe_m) >= abs(dce_m) else "ce"
        _, read = classify(side, dpe_m if side == "pe" else dce_m)
        marker = " <-ATM" if k == min((x["strike"] for x in snap["strikes"]),
                                      key=lambda kk: abs(kk - spot)) else ""
        print(f"{fmt(k,0):>8} | {s['ce_oi']:>11,} {dce_m:>+11,} {dce_p:>+10,} | "
              f"{s['pe_oi']:>11,} {dpe_m:>+11,} {dpe_p:>+10,} | {read}{marker}")

        # event detection: per leg, significant move vs morning baseline
        for leg, oi_now, d_morn, d_prev, base_oi in (
            ("ce", s["ce_oi"], dce_m, dce_p, (b["ce_oi"] if b else 0)),
            ("pe", s["pe_oi"], dpe_m, dpe_p, (b["pe_oi"] if b else 0)),
        ):
            pct = (100.0 * d_morn / base_oi) if base_oi else 0.0
            big = abs(d_morn) >= thr_abs if thr_abs > 0 else abs(pct) >= thr_pct
            if not history or not big:
                continue
            action, read2 = classify(leg, d_morn)
            events.append({
                "ts": snap["ts"], "symbol": symbol, "expiry": expiry, "seq": seq,
                "strike": k, "leg": leg.upper(), "oi": oi_now,
                "d_morning": d_morn, "d_prev": d_prev, "pct_morning": round(pct, 1),
                "action": action, "read": read2,
            })

    if events:
        print("\n--- EVENTS (significant OI shift vs morning) ---")
        for e in sorted(events, key=lambda e: -abs(e["d_morning"])):
            _append_jsonl(ev_path, e)
            print(f"  {fmt(e['strike'],0):>8} {e['leg']}  {e['d_morning']:>+12,} "
                  f"({e['pct_morning']:>+6.1f}%)  {e['action']:<14} {e['read']}")
        print(f"  ({len(events)} event(s) appended -> {ev_path.name})")
    elif history:
        print(f"\n(no moves >= {thr_abs:,} abs / {thr_pct:.0f}% vs morning this snapshot)")
    print(f"snapshots -> {snap_path}")

    if sinks is not None:
        sinks.write(snap, events)


def resolve_expiry(client, sec_id: int, seg: str, override: str | None, today: date) -> str:
    expiries = fetch_expiries(client, sec_id, seg)
    if not expiries:
        raise RuntimeError("no expiries returned (check data-plan / token)")
    if override:
        return override
    future = [e for e in expiries if e >= today.isoformat()]
    return future[0] if future else expiries[0]


def run_analysis(client, symbol: str, sec_id: int, seg: str, expiry: str, is_today: bool, vix: float | None) -> None:
    print(f"\n=== {symbol} option-chain analysis  expiry {expiry} "
          f"({'TODAY — expiry day' if is_today else 'nearest available'}) ===")
    if not is_today:
        print("  NOTE: today is not this expiry; treat 'close' as the expiry-day projection.")

    time.sleep(1.1)  # respect 1 req/sec on the chain (quote) API
    spot, rows = fetch_chain(client, sec_id, seg, expiry)
    rows = [r for r in rows if (r["ce_oi"] or r["pe_oi"])]  # drop empty strikes
    print(f"Spot (last_price): {fmt(spot)}   India VIX: {fmt(vix)}")

    mp = max_pain(rows)
    pc = pcr(rows)
    atm = atm_row(rows, spot)
    straddle = (atm["ce_ltp"] or 0) + (atm["pe_ltp"] or 0)
    vix_move = spot * (vix / 100.0) * math.sqrt(1 / 365.0) if vix else None

    # IV skew: nearest 3 OTM puts vs 3 OTM calls
    otm_p = sorted([r for r in rows if r["strike"] < spot], key=lambda r: -r["strike"])[:3]
    otm_c = sorted([r for r in rows if r["strike"] > spot], key=lambda r: r["strike"])[:3]
    piv = [r["pe_iv"] for r in otm_p if r["pe_iv"]]
    civ = [r["ce_iv"] for r in otm_c if r["ce_iv"]]
    skew = (sum(piv) / len(piv) - sum(civ) / len(civ)) if piv and civ else None

    print("\n--- Analytics ---")
    print(f"Max pain        : {fmt(mp,0)}   (vs spot {fmt(spot,0)}  -> diff {fmt(mp-spot,0)})")
    print(f"PCR (OI)        : {fmt(pc)}   ({'bullish/supportive' if pc>1 else 'bearish/cautious' if pc<0.8 else 'neutral'})")
    print(f"ATM strike      : {fmt(atm['strike'],0)}  | ATM straddle = {fmt(straddle)}  (~expected move by expiry)")
    if vix_move is not None:
        print(f"VIX-implied 1d move: +/-{fmt(vix_move)}  ->  range {fmt(spot-vix_move,0)} .. {fmt(spot+vix_move,0)}")
    print(f"IV skew (P-C)   : {fmt(skew)}   ({'downside fear' if skew and skew>0 else 'upside chase' if skew and skew<0 else 'flat'})")
    print(f"ATM delta CE/PE : {fmt(atm['ce_delta'])} / {fmt(atm['pe_delta'])}  | ATM gamma CE/PE: {fmt(atm['ce_gamma'],5)} / {fmt(atm['pe_gamma'],5)}")

    print("\n--- OI walls (strike, OI, dOI) ---")
    print("CALL OI (resistance):")
    for k, oi, doi in top_oi(rows, "ce"):
        print(f"   {fmt(k,0):>10}  OI={oi:>12,}  dOI={doi:>+12,}")
    print("PUT OI (support):")
    for k, oi, doi in top_oi(rows, "pe"):
        print(f"   {fmt(k,0):>10}  OI={oi:>12,}  dOI={doi:>+12,}")

    # crude expected band: between dominant PE wall (support) and CE wall (resistance)
    top_ce = top_oi(rows, "ce")[0][0]
    top_pe = top_oi(rows, "pe")[0][0]
    lo, hi = sorted((top_pe, top_ce))
    print("\n--- Read ---")
    print(f"OI-wall band    : {fmt(lo,0)} (support) .. {fmt(hi,0)} (resistance)")
    print(f"Max-pain magnet : {fmt(mp,0)}")
    print("(Synthesis / verdict written up separately — this is the raw evidence.)\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Index option-chain expiry analysis + OI tracker (read-only)")
    ap.add_argument("--symbol", default="NIFTY,BANKNIFTY,SENSEX",
                    help="comma list of indices to watch, or ALL. "
                         f"choices: {', '.join(UNDERLYINGS)}. "
                         "default: NIFTY,BANKNIFTY,SENSEX (e.g. --symbol NIFTY  or  --symbol NIFTY,BANKNIFTY)")
    ap.add_argument("--expiry", default=None,
                    help="ISO YYYY-MM-DD; only valid with a single --symbol (else per-symbol nearest)")
    ap.add_argument("--track", action="store_true",
                    help="OI snapshot mode: persist ATM+/-N OI and diff vs morning/prev")
    ap.add_argument("--strikes", type=int, default=5, help="ATM +/- N strikes to track (default 5)")
    ap.add_argument("--interval", type=int, default=0,
                    help="if >0, loop the tracker every N seconds (e.g. 300 = 5 min)")
    ap.add_argument("--event-threshold-pct", type=float, default=15.0,
                    help="flag an event when |OI change vs morning| >= this %% (default 15)")
    ap.add_argument("--event-threshold-abs", type=int, default=0,
                    help="absolute-OI event threshold; overrides the %% threshold when > 0")
    ap.add_argument("--store", default="mongo,redis",
                    help="extra sinks for --track snapshots: comma list of mongo,redis or none "
                         "(JSONL local history is always written). Default: mongo,redis")
    args = ap.parse_args()

    if args.symbol.strip().upper() == "ALL":
        symbols = list(UNDERLYINGS)
    else:
        symbols = [s.strip().upper() for s in args.symbol.split(",") if s.strip()]
    unknown = [s for s in symbols if s not in UNDERLYINGS]
    if unknown:
        raise SystemExit(f"unknown symbol(s): {unknown}; choose from {list(UNDERLYINGS)}")
    if args.expiry and len(symbols) > 1:
        raise SystemExit("--expiry only valid with a single --symbol")

    client = _make_client()
    today = date.today()
    now = datetime.now(IST)

    # Resolve each symbol's nearest expiry once up front.
    plan: list[tuple[str, int, str, str]] = []  # (symbol, sec_id, seg, expiry)
    for sym in symbols:
        sec_id, seg = UNDERLYINGS[sym]
        try:
            expiry = resolve_expiry(client, sec_id, seg, args.expiry, today)
        except Exception as exc:  # noqa: BLE001 - one bad symbol shouldn't kill the run
            print(f"[{sym}] skipped: {exc}")
            continue
        plan.append((sym, sec_id, seg, expiry))

    if not plan:
        raise SystemExit("no symbols resolved — nothing to watch")
    watching = ", ".join(f"{sym}@{expiry}" for sym, _, _, expiry in plan)

    if args.track:
        targets = {t.strip().lower() for t in args.store.split(",") if t.strip() and t.strip().lower() != "none"}
        sinks = Sinks(targets) if targets else None
        loop = f"every {args.interval}s" if args.interval > 0 else "single pass"
        print(f"watching {len(plan)} index(es): {watching}  |  {loop}  |  ATM+/-{args.strikes}")

        def _one_pass() -> None:
            for sym, sec_id, seg, expiry in plan:
                time.sleep(1.1)  # respect 1 req/sec on the chain (quote) API
                try:
                    spot, rows = fetch_chain(client, sec_id, seg, expiry)
                except Exception as exc:  # noqa: BLE001
                    print(f"[{sym}] chain fetch failed: {exc}")
                    continue
                rows = [r for r in rows if (r["ce_oi"] or r["pe_oi"])]
                track_oi(sym, expiry, spot, rows, args.strikes,
                         args.event_threshold_pct, args.event_threshold_abs, sinks)

        _one_pass()
        while args.interval > 0:
            try:
                time.sleep(max(1, args.interval - 1.1 * len(plan)))  # ~interval minus chain calls
                _one_pass()
            except KeyboardInterrupt:
                print("\nstopped.")
                break
        return

    print(f"\n########## option-chain analysis @ {now:%Y-%m-%d %H:%M:%S} IST ##########")
    vix = fetch_india_vix(client)  # shared India VIX read (one quote call for the whole run)
    for sym, sec_id, seg, expiry in plan:
        is_today = expiry == today.isoformat()
        try:
            run_analysis(client, sym, sec_id, seg, expiry, is_today, vix)
        except Exception as exc:  # noqa: BLE001
            print(f"[{sym}] analysis failed: {exc}")


if __name__ == "__main__":
    main()
