"""Seed the DB-backed ``expiry_calendar`` from exchange F&O bhavcopy archives (NSE + BSE).

The authoritative historical source for *real* index-option expiry dates — independent of what we
happen to hold in ``option_bars`` — so it can fill the genuine coverage gaps (NIFTY's 763-day
2020-2023 blackout, the ~25 small weekly-cadence gaps) that ``seed_expiry_calendar.py
--from-option-bars`` structurally *cannot* (a date absent from ``option_bars`` can't be derived
from it). See ``option-bars-expiry-gap-backfill``.

Every daily F&O bhavcopy lists all currently-listed contracts and their expiry dates. Weeklies are
always listed at least a week ahead, so sampling one bhavcopy per week and unioning the distinct
index-option expiry dates captures *every* weekly expiry over the range. Both exchanges are covered:

  * **NSE** (NIFTY, BANKNIFTY) — ``nsearchives.nseindia.com``. Two formats handled transparently:
      pre-2024-07 legacy zip ``.../historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip``
        (``INSTRUMENT=OPTIDX, SYMBOL, EXPIRY_DT`` ``%d-%b-%Y``)
      2024-07+ UDiFF zip ``.../fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip``
  * **BSE** (SENSEX, BANKEX) — ``bseindia.com`` UDiFF plain CSV
      ``.../BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_YYYYMMDD_F_0000.CSV`` (needs a Referer header;
      SENSEX weekly options only launched mid-2023, so earlier dates simply have no rows).

  Both UDiFF layouts share columns ``FinInstrmTp=IDO, TckrSymb, XpryDt`` (``%Y-%m-%d``) and the
  market lot ``NewBrdLotQty``.

``--exchange auto`` routes NIFTY/BANKNIFTY→NSE and SENSEX/BANKEX→BSE, so one command seeds all
three indices. Downloads are cached (``--cache-dir``) so re-runs are cheap and resumable.
Idempotent: upserts into ``expiry_calendar`` keyed ``(underlying, flag, expiry_date)`` with
``source="nse_archive"``/``"bse_archive"``, stamping ``expiry_weekday`` + ``lot_size``.

Usage:
  python scripts/seed_expiry_from_bhavcopy.py --from 2020-01-01 --to 2026-07-14        # all 3 (auto)
  python scripts/seed_expiry_from_bhavcopy.py --symbols SENSEX --from 2023-05-01 --to 2026-07-14
  python scripts/seed_expiry_from_bhavcopy.py --symbols NIFTY --from 2020-12-01 --to 2023-02-01
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pymongo import MongoClient

from pdp.instruments.expiry_calendar import classify_month_expiries, upsert_confirmed_expiries
from pdp.settings import get_settings

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_UDIFF_START = date(2024, 7, 8)  # NSE cut over to UDiFF here; before that the legacy zip is used.
_EXCH_OF = {"NIFTY": "nse", "BANKNIFTY": "nse", "SENSEX": "bse", "BANKEX": "bse"}
_SOURCE = {"nse": "nse_archive", "bse": "bse_archive"}


def _urls_for(d: date, exchange: str) -> list[str]:
    """Candidate bhavcopy URLs for a trading day (era-appropriate first, other as fallback)."""
    ymd = d.strftime("%Y%m%d")
    if exchange == "bse":
        return [f"https://www.bseindia.com/download/BhavCopy/Derivative/"
                f"BhavCopy_BSE_FO_0_0_0_{ymd}_F_0000.CSV"]
    udiff = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
    mon = _MON[d.month - 1]
    legacy = (f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
              f"{d.year}/{mon}/fo{d.day:02d}{mon}{d.year}bhav.csv.zip")
    return [udiff, legacy] if d >= _UDIFF_START else [legacy, udiff]


def _cache_name(d: date, exchange: str) -> str:
    return f"{'fo' if exchange == 'nse' else exchange}_{d.strftime('%Y%m%d')}.bin"


def _looks_like_bhav(data: bytes) -> bool:
    """True if ``data`` is a real bhavcopy (zip or CSV), not a homepage/error HTML page.

    BSE serves its homepage with HTTP 200 for a non-trading day (rather than a 404), so a payload
    must be content-checked or those HTML pages get cached as if they were data — and any weekly
    sampling cadence that lands on a Sunday would then silently collect nothing.
    """
    if data[:2] == b"PK":  # zip (NSE)
        return True
    return data[:64].lstrip().lower().startswith((b"traddt", b"instrument"))  # UDiFF / legacy CSV


def _fetch(d: date, cache_dir: Path, exchange: str, *, retries: int = 3) -> bytes | None:
    """Return the bhavcopy bytes for trading day ``d`` (cached), or ``None`` if not a trade day."""
    cache = cache_dir / _cache_name(d, exchange)
    if cache.exists():
        data = cache.read_bytes()
        return data if data else None  # empty sentinel = known non-trading day
    headers = {"User-Agent": _UA}
    if exchange == "bse":
        headers["Referer"] = "https://www.bseindia.com/"
    for url in _urls_for(d, exchange):
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=headers)  # noqa: S310 (trusted exchange host)
                with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                    data = resp.read()
                if not _looks_like_bhav(data):
                    break  # non-trading-day homepage / error HTML -> treat as miss, try next url
                cache.write_bytes(data)
                return data
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    break  # try the other format / give up on this day
                time.sleep(0.5 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.5 * (attempt + 1))
    cache.write_bytes(b"")  # cache the miss so re-runs skip weekends/holidays instantly
    return None


def _csv_text(data: bytes) -> str:
    """Decode a bhavcopy payload to CSV text — unzipping first if it is a zip (NSE), else raw (BSE)."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def _expiries_from_bhav(data: bytes, symbols: set[str]) -> dict[str, dict[date, int | None]]:
    """Index-option expiry dates (-> market lot, or None) per symbol in one bhavcopy payload.

    The lot size comes from the UDiFF ``NewBrdLotQty`` column; the legacy NSE format carries no lot
    column, so those expiries map to ``None`` and are enriched later if a UDiFF listing of the same
    expiry is also seen.
    """
    out: dict[str, dict[date, int | None]] = {s: {} for s in symbols}
    reader = csv.DictReader(io.StringIO(_csv_text(data)))
    fields = {(f or "").strip() for f in (reader.fieldnames or [])}
    udiff = "FinInstrmTp" in fields
    for raw_row in reader:
        # BSE data rows carry a trailing extra field -> DictReader puts the overflow in a list
        # under the restkey (None). Keep only the named string columns.
        row = {
            k.strip(): (v.strip() if isinstance(v, str) else "")
            for k, v in raw_row.items()
            if isinstance(k, str)
        }
        if udiff:
            if row.get("FinInstrmTp") != "IDO":
                continue
            sym, raw, fmt = row.get("TckrSymb", ""), row.get("XpryDt", ""), "%Y-%m-%d"
            lot_raw = row.get("NewBrdLotQty", "")
        else:
            if row.get("INSTRUMENT") != "OPTIDX":
                continue
            sym, raw, fmt, lot_raw = row.get("SYMBOL", ""), row.get("EXPIRY_DT", ""), "%d-%b-%Y", ""
        if sym not in symbols or not raw:
            continue
        try:
            exp = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        lot = int(lot_raw) if lot_raw.isdigit() and int(lot_raw) > 0 else None
        if out[sym].get(exp) is None:  # first non-null lot wins; keep the date even if lot unknown
            out[sym][exp] = lot
    return out


def sweep(
    symbols: set[str], d0: date, d1: date, cache_dir: Path, step: int, exchange: str
) -> dict[str, dict[date, int | None]]:
    """Union of index-option expiries (-> lot) per symbol across weekly bhavcopies in [d0, d1]."""
    found: dict[str, dict[date, int | None]] = {s: {} for s in symbols}
    cur, n_days, n_hit = d0, 0, 0
    while cur <= d1:
        # nudge forward off weekends/holidays to the next available trading-day bhavcopy
        data, probe = None, cur
        for _ in range(5):
            data = _fetch(probe, cache_dir, exchange)
            if data is not None:
                break
            probe += timedelta(days=1)
        n_days += 1
        if data is not None:
            n_hit += 1
            for sym, exps in _expiries_from_bhav(data, symbols).items():
                for exp, lot in exps.items():
                    if found[sym].get(exp) is None:
                        found[sym][exp] = lot
        if n_days % 25 == 0:
            print(f"  [{exchange}] ... {n_days} weeks sampled ({n_hit} bhavcopies), "
                  f"{ {s: len(v) for s, v in found.items()} }", flush=True)
        time.sleep(0.2)
        cur += timedelta(days=step)
    print(f"  [{exchange}] swept {n_days} weekly samples, {n_hit} bhavcopies downloaded/cached")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed expiry_calendar from NSE/BSE bhavcopy archives.")
    ap.add_argument("--symbols", nargs="+", default=["NIFTY", "BANKNIFTY", "SENSEX"],
                    help="Index-option underlyings (default: all three)")
    ap.add_argument("--exchange", choices=["auto", "nse", "bse"], default="auto",
                    help="auto routes NIFTY/BANKNIFTY->NSE, SENSEX/BANKEX->BSE")
    ap.add_argument("--from", dest="d0", required=True, help="Sweep start YYYY-MM-DD")
    ap.add_argument("--to", dest="d1", required=True, help="Sweep end YYYY-MM-DD")
    ap.add_argument("--step", type=int, default=7, help="Days between samples (7 = weekly, safe)")
    ap.add_argument("--upper-pad", type=int, default=45,
                    help="Keep expiries only up to --to + this many days (drops stray far-months)")
    ap.add_argument("--cache-dir", default=None, help="Bhavcopy cache dir (default: ./.bhav_cache)")
    ap.add_argument("--dry-run", action="store_true", help="Report found expiries; do not write DB")
    a = ap.parse_args()

    symbols = [s.upper() for s in a.symbols]
    d0, d1 = date.fromisoformat(a.d0), date.fromisoformat(a.d1)
    upper = d1 + timedelta(days=a.upper_pad)
    cache_dir = Path(a.cache_dir) if a.cache_dir else Path.cwd() / ".bhav_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # group symbols by the exchange each trades on (one bhavcopy sweep serves all of that exchange)
    by_exch: dict[str, set[str]] = {}
    for sym in symbols:
        exch = a.exchange if a.exchange != "auto" else _EXCH_OF.get(sym, "nse")
        by_exch.setdefault(exch, set()).add(sym)

    found: dict[str, dict[date, int | None]] = {}
    exch_of: dict[str, str] = {}
    for exch, syms in by_exch.items():
        print(f"\n{exch.upper()} sweep {d0}..{d1} step={a.step}d symbols={sorted(syms)}")
        result = sweep(syms, d0, d1, cache_dir, a.step, exch)
        found.update(result)
        for s in syms:
            exch_of[s] = exch

    total_new = 0
    mdb = None
    if not a.dry_run:
        s = get_settings()
        mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
        mdb["expiry_calendar"].create_index(
            [("underlying", 1), ("flag", 1), ("expiry_date", 1)],
            unique=True, name="uq_underlying_flag_expiry",
        )

    for sym in sorted(symbols):
        exps = sorted(e for e in found[sym] if d0 <= e <= upper)
        lot_by_date = {e: lot for e in exps if (lot := found[sym][e]) is not None}
        week_list, month_list = classify_month_expiries(exps)
        rng = f"{exps[0]}..{exps[-1]}" if exps else "none"
        print(f"\n{sym} ({exch_of[sym]}): {len(exps)} real expiries in range ({rng}); "
              f"WEEK={len(week_list)} MONTH={len(month_list)}; lot known for {len(lot_by_date)}")
        if a.dry_run or mdb is None:
            print(f"  [dry-run] would upsert WEEK {len(week_list)} + MONTH {len(month_list)}")
            continue
        src = _SOURCE[exch_of[sym]]
        n_w = upsert_confirmed_expiries(mdb, sym, "WEEK", week_list, source=src, lot_by_date=lot_by_date)
        n_m = upsert_confirmed_expiries(mdb, sym, "MONTH", month_list, source=src, lot_by_date=lot_by_date)
        print(f"  upserted: WEEK +{n_w} new, MONTH +{n_m} new")
        total_new += n_w + n_m

    print(f"\ntotal newly inserted: {total_new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
