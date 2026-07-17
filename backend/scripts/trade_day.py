"""
trade_day.py — Pre-market checks + live monitoring dashboard for 3-index paper trading.

Usage (run from backend/ directory):
    python scripts/trade_day.py            # pre-checks → live monitor
    python scripts/trade_day.py check      # pre-checks only, then exit
    python scripts/trade_day.py monitor    # live monitor only (API must be running)
    python scripts/trade_day.py validate --expected path/to/kite_values.json
                                            # one-shot value-by-value diff against
                                            # hand-entered Kite values (indicator-matrix-kite-parity)

Endpoints used:
    GET /healthz                              API alive
    GET /readyz                               DB / Redis / Mongo health
    GET /api/v1/strategies                    strategy list + status
    GET /api/v1/strangle/status?strategy_id=  per-strategy state
    GET /api/v1/instruments?underlying=X&limit=1  instruments check
    GET /api/v1/strangle/monitor               full indicator matrix (used by `monitor`/`validate`)
    http://localhost:9200/                    OpenSearch health
    http://localhost:5601/                    OpenSearch Dashboards
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import httpx
except ImportError:
    print("httpx not installed — run:  uv pip install httpx")
    sys.exit(1)

API = "http://localhost:8000"
_OS_URL = "http://localhost:9200"
_KB_URL = "http://localhost:5601"
_IST = ZoneInfo("Asia/Kolkata")
_STRATEGIES = [
    "directional_strangle_nifty",
    "directional_strangle_banknifty",
    "directional_strangle_sensex",
]
_UNDERLYINGS = ["NIFTY", "BANKNIFTY", "SENSEX"]
_INDEX_SID_LABEL = {"13": "NIFTY", "25": "BANKNIFTY", "51": "SENSEX"}
_IND_TFS = ["5m", "15m", "30m", "1H", "1D"]

# ── ANSI helpers ──────────────────────────────────────────────────────────────
R = "\033[91m"   # red
G = "\033[92m"   # green
Y = "\033[93m"   # yellow
B = "\033[94m"   # blue
C = "\033[96m"   # cyan
W = "\033[97m"   # white
Z = "\033[0m"    # reset
BD = "\033[1m"   # bold
DM = "\033[2m"   # dim
CLS = "\033[2J\033[H"  # clear + home

def _ok(msg: str)  -> None: print(f"  {G}✓{Z}  {msg}")
def _warn(msg: str) -> None: print(f"  {Y}!{Z}  {msg}")
def _err(msg: str)  -> None: print(f"  {R}✗{Z}  {msg}")
def _hdr(msg: str)  -> None: print(f"\n{BD}{B}{msg}{Z}")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(path: str, **params) -> dict | list | None:
    try:
        r = httpx.get(f"{API}{path}", params=params, timeout=3)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ── Environment check ─────────────────────────────────────────────────────────

def _read_dotenv() -> dict[str, str]:
    env: dict[str, str] = {}
    dotenv = Path(__file__).parent.parent / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN", "LIVE"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


# ── Pre-checks ────────────────────────────────────────────────────────────────

def pre_checks() -> bool:
    now_ist = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"\n{BD}{W}{'═'*56}{Z}")
    print(f"{BD}{W}  PDP Paper Trade — Pre-Market Checks  {DM}{now_ist}{Z}")
    print(f"{BD}{W}{'═'*56}{Z}")

    all_green = True

    # 1. API alive
    _hdr("1. API")
    health = _get("/healthz")
    if health and health.get("status") == "ok":
        _ok(f"API running — started_at={health.get('started_at', '?')}")
    else:
        _err("API not reachable — run:  task db:up && task db:migrate && task dev")
        print(f"\n  {Y}Start the API first, then re-run this script.{Z}\n")
        return False

    # 2. DB / Redis / Mongo
    _hdr("2. Infrastructure")
    ready = _get("/readyz")
    if ready:
        for svc in ("db", "redis", "mongo"):
            st = ready.get(svc, "?")
            if st == "ok":
                _ok(f"{svc:<8} OK")
            else:
                _err(f"{svc:<8} {st}")
                all_green = False
    else:
        _warn("Could not reach /readyz — infrastructure state unknown")

    # 3. Strategies
    _hdr("3. Strategies")
    strats_raw = _get("/api/v1/strategies")
    strats: dict[str, dict] = {}
    if isinstance(strats_raw, dict) and "strategies" in strats_raw:
        strats = {s["id"]: s for s in strats_raw["strategies"]}
    elif isinstance(strats_raw, list):
        strats = {s["id"]: s for s in strats_raw}
    for sid in _STRATEGIES:
        label = sid.replace("directional_strangle_", "")
        if sid in strats:
            mode = strats[sid].get("mode", "?")
            status = strats[sid].get("status", "?")
            color = G if status == "active" else Y
            _ok(f"{label:<12}  [{color}{status}{Z}]  mode={mode}")
        else:
            _err(f"{label:<12}  NOT LOADED — check API log for import errors")
            all_green = False

    # 4. Instruments
    _hdr("4. Instruments (today's expiry in DB)")
    for underlying in _UNDERLYINGS:
        rows = _get("/api/v1/instruments", underlying=underlying, limit=1)
        if rows:
            _ok(f"{underlying:<12}  found in instruments table")
        else:
            _warn(f"{underlying:<12}  no rows found — scrip master may not be loaded")
            _warn(f"             Restart API (auto-loads on startup when DHAN_CLIENT_ID is set)")
            all_green = False

    # 5. Environment / credentials
    _hdr("5. Environment")
    env = _read_dotenv()
    cid = env.get("DHAN_CLIENT_ID", "")
    tok = env.get("DHAN_ACCESS_TOKEN", "")
    live = env.get("LIVE", "0")

    if cid:
        _ok(f"DHAN_CLIENT_ID    set ({cid[:4]}...{cid[-3:]})")
    else:
        _warn("DHAN_CLIENT_ID    not set — tick feed will use mock source (no real prices)")
    if tok:
        _ok(f"DHAN_ACCESS_TOKEN set ({tok[:6]}...)")
    else:
        _warn("DHAN_ACCESS_TOKEN not set — tick feed will use mock source")
    if live == "1":
        _err(f"{BD}LIVE=1 is set — REAL ORDERS WILL BE PLACED! Set LIVE=0 for paper.{Z}")
        all_green = False
    else:
        _ok("LIVE              0 (paper mode)")

    # 6. OpenSearch observability (optional but recommended)
    _hdr("6. Observability (OpenSearch)")
    try:
        os_resp = httpx.get(f"{_OS_URL}/", timeout=2)
        os_data = os_resp.json() if os_resp.status_code == 200 else {}
        version = os_data.get("version", {}).get("number", "?")
        _ok(f"OpenSearch {version} reachable at {_OS_URL}")
    except Exception:
        _warn(f"OpenSearch not reachable — run:  task search:up && task search:init")
        _warn(f"  (Logs still captured to stdout/JSONL; dashboards won't work)")
    try:
        kb_resp = httpx.get(f"{_KB_URL}/", timeout=2)
        if kb_resp.status_code in (200, 302):
            _ok(f"Dashboards at {C}{_KB_URL}{Z}  (login: admin / admin)")
        else:
            _warn(f"Dashboards returned HTTP {kb_resp.status_code}")
    except Exception:
        _warn(f"Dashboards not reachable — start with:  task search:up")

    # Summary
    print(f"\n{BD}{'═'*56}{Z}")
    if all_green:
        print(f"  {G}{BD}All checks passed ✓  Ready to trade.{Z}")
    else:
        print(f"  {Y}{BD}Some warnings above — review before trading.{Z}")
    print(f"{BD}{'═'*56}{Z}\n")

    return all_green


# ── Monitor dashboard ─────────────────────────────────────────────────────────

_BUCKET_COLOR: dict[str, str] = {
    "complete_bull": G + BD,
    "most_bull":     G,
    "more_bull":     G,
    "neutral":       Y,
    "more_bear":     R,
    "most_bear":     R,
    "complete_bear": R + BD,
}


def _fmt_bucket(b: str | None) -> str:
    if not b:
        return f"{DM}—{Z}"
    c = _BUCKET_COLOR.get(b, Z)
    return f"{c}{b}{Z}"


def _fmt_pnl(val: float | None) -> str:
    if val is None:
        return f"{DM}—{Z}"
    c = G if val >= 0 else R
    return f"{c}{val:+,.0f}{Z}"


def _fmt_score(score: float | None) -> str:
    if score is None:
        return f"{DM}—{Z}"
    c = G if score > 0.1 else R if score < -0.1 else Y
    return f"{c}{score:+.3f}{Z}"


def _fmt_price(val: float | None) -> str:
    if val is None or val == 0.0:
        return f"{DM}—{Z}"
    return f"{val:,.2f}"


def _fmt_mtm(val: float | None) -> str:
    if val is None:
        return f"{DM}—{Z}"
    c = G if val >= 0 else R
    return f"{c}{val:+,.0f}{Z}"


def _leg_type(leg: dict) -> str:
    if leg.get("is_hedge"):
        return f"{DM}HEDGE{Z}"
    if leg.get("is_momentum"):
        return f"{Y}MOMTM{Z}"
    return f"{BD}SHORT{Z}"


def _leg_opt(leg: dict) -> str:
    ot = leg.get("opt_type", "?")
    return f"{R}{ot}{Z}" if ot == "PE" else f"{B}{ot}{Z}"


def _fmt_ind(val: float | None, dp: int = 1) -> str:
    if val is None:
        return f"{DM}--{Z}"
    return f"{val:,.{dp}f}"


_CAM_PERIOD_FOR_TF = {"5m": "daily", "15m": "daily", "30m": "weekly", "1H": "weekly", "1D": "monthly"}

_ATM_ROW_LABEL = {"NIFTY_ATM_CE": "NIFTY ATM CE", "NIFTY_ATM_PE": "NIFTY ATM PE"}


def _st_variant_disp(c: dict, key: str) -> str:
    v = c.get(key) or {}
    arrow = "^" if v.get("direction") == "up" else ("v" if v.get("direction") == "down" else "")
    val = v.get("value")
    return f"{_fmt_ind(val)}{arrow}" if val is not None else f"{DM}--{Z}"


def _indicator_lines(mon: dict | None) -> list[str]:
    """Full validation-harness dump: EMA/3xST/PSAR/RSI/VWAP/VWMA matrix per
    underlying x timeframe, PDH/PDL/PWH/PWL/PMH/PML + Camarilla (period per the
    5m/15m->daily, 30m/1H->weekly, 1D->monthly mapping), and the NIFTY ATM CE/PE
    rows — everything `GET /api/v1/strangle/monitor` serves for the Kite-parity
    validation described in indicator-matrix-kite-parity. A `--` on ema200 means
    warmup hasn't fed 200 bars for that timeframe yet — see
    memory/execution_console_accuracy.md.
    """
    lines: list[str] = []
    if not mon:
        return lines
    indicators: dict = mon.get("indicators") or {}

    def _cell_row(tf: str, c: dict) -> str:
        return (
            f"  {tf:<5} {_st_variant_disp(c, 'st_10_2'):>10} {_st_variant_disp(c, 'st_10_3'):>10} "
            f"{_st_variant_disp(c, 'st_3_1'):>9} {_fmt_ind(c.get('ema9')):>9} "
            f"{_fmt_ind(c.get('ema20')):>9} {_fmt_ind(c.get('ema50')):>9} "
            f"{_fmt_ind(c.get('ema100')):>9} {_fmt_ind(c.get('ema200')):>9} "
            f"{_fmt_ind(c.get('psar')):>9} {_fmt_ind(c.get('rsi'), 1):>6} "
            f"{_fmt_ind(c.get('vwap')):>9} {_fmt_ind(c.get('vwma')):>9}"
        )

    header = (
        f"  {DM}{'TF':<5} {'ST(10,2)':>10} {'ST(10,3)':>10} {'ST(3,1)':>9} {'EMA9':>9} "
        f"{'EMA20':>9} {'EMA50':>9} {'EMA100':>9} {'EMA200':>9} {'PSAR':>9} {'RSI':>6} "
        f"{'VWAP':>9} {'VWMA':>9}{Z}"
    )

    for sid, label in _INDEX_SID_LABEL.items():
        sid_data = indicators.get(sid) or {}
        cell_by_tf = sid_data.get("tf") or {}
        if not cell_by_tf:
            continue
        lines.append(f"\n  {BD}{W}{label} indicators{Z}")
        lines.append(header)
        for tf in _IND_TFS:
            c = cell_by_tf.get(tf)
            if not c:
                continue
            lines.append(_cell_row(tf, c))

        period = sid_data.get("period") or {}
        lines.append(
            f"  {DM}PDH {_fmt_ind(period.get('pdh'))}  PDL {_fmt_ind(period.get('pdl'))}  "
            f"PWH {_fmt_ind(period.get('pwh'))}  PWL {_fmt_ind(period.get('pwl'))}  "
            f"PMH {_fmt_ind(period.get('pmh'))}  PML {_fmt_ind(period.get('pml'))}{Z}"
        )
        for cam_period in ("daily", "weekly", "monthly"):
            cam = sid_data.get(f"camarilla_{cam_period}") or {}
            if not cam:
                continue
            lines.append(
                f"  {DM}Camarilla({cam_period:<7}){Z} R4 {_fmt_ind(cam.get('r4'))}  "
                f"R3 {_fmt_ind(cam.get('r3'))}  S3 {_fmt_ind(cam.get('s3'))}  "
                f"S4 {_fmt_ind(cam.get('s4'))}"
            )

    # NIFTY ATM CE/PE rows — same cell shape, no Camarilla/period levels.
    for key, row_label in _ATM_ROW_LABEL.items():
        row = indicators.get(key)
        if not row:
            continue
        cell_by_tf = row.get("tf") or {}
        strike = row.get("strike")
        expiry = row.get("expiry")
        lines.append(f"\n  {BD}{W}{row_label} (strike {strike}, expiry {expiry}){Z}")
        lines.append(header)
        for tf in _IND_TFS:
            c = cell_by_tf.get(tf)
            if not c:
                continue
            lines.append(_cell_row(tf, c))

    return lines


# ── --expected diff harness ───────────────────────────────────────────────────

def _flatten_expected(prefix: str, cell: dict) -> dict[str, float]:
    """Flatten a hand-entered expected cell into dotted keys matching the live
    cell's own field names, so a diff can walk both by the same key set."""
    out: dict[str, float] = {}
    for k, v in cell.items():
        if isinstance(v, dict):
            out.update(_flatten_expected(f"{prefix}.{k}", v))
        elif isinstance(v, (int, float)):
            out[f"{prefix}.{k}"] = float(v)
    return out


def _flatten_live_cell(prefix: str, cell: dict, keys: set[str]) -> dict[str, float | None]:
    """Pull only the dotted keys the expected file asked about, from a live cell
    (handling the nested st_10_2/st_10_3/st_3_1 variant dicts)."""
    out: dict[str, float | None] = {}
    for key in keys:
        if not key.startswith(f"{prefix}."):
            continue
        parts = key[len(prefix) + 1:].split(".")
        node: Any = cell
        for p in parts:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(p)
        out[key] = float(node) if isinstance(node, (int, float)) else None
    return out


def _run_validation(mon: dict | None, expected_path: str, tolerance: float) -> int:
    """Diff the live monitor snapshot against a hand-entered `--expected` JSON file.

    Expected file shape: {"<SID_OR_ROW_KEY>": {"<tf>": {"ema9": 24213.0, "st_10_2":
    {"value": ..., "direction": "up"}, ...}, "camarilla_daily": {"r4": ...}, "period":
    {"pmh": ...}}}. Each numeric leaf is compared to the live value within `tolerance`
    points; a missing live value is reported as a distinct failure (still-stale/unseeded),
    not silently skipped.
    """
    import json as _json

    with open(expected_path, encoding="utf-8") as f:
        expected = _json.load(f)

    if not mon:
        print(f"  {R}No live monitor data — is the API running?{Z}")
        return 1

    indicators: dict = mon.get("indicators") or {}
    n_checked = 0
    n_failed = 0

    for row_key, row_expected in expected.items():
        live_row = indicators.get(row_key)
        label = _INDEX_SID_LABEL.get(row_key, _ATM_ROW_LABEL.get(row_key, row_key))
        print(f"\n  {BD}{W}{label}{Z}")
        if live_row is None:
            print(f"    {R}✗ no live data for {row_key}{Z}")
            n_failed += 1
            continue

        for section, section_expected in row_expected.items():
            live_section = live_row.get(section) if section != "tf" else None
            if section == "tf":
                for tf, tf_expected in section_expected.items():
                    live_cell = (live_row.get("tf") or {}).get(tf) or {}
                    flat_expected = _flatten_expected(f"{row_key}.tf.{tf}", tf_expected)
                    flat_live = _flatten_live_cell(f"{row_key}.tf.{tf}", live_cell, set(flat_expected))
                    for key, exp_val in flat_expected.items():
                        n_checked += 1
                        live_val = flat_live.get(key)
                        if live_val is None:
                            print(f"    {R}✗ {key}: expected {exp_val}, live is -- (unseeded){Z}")
                            n_failed += 1
                        elif abs(live_val - exp_val) > tolerance:
                            print(f"    {R}✗ {key}: expected {exp_val}, live {live_val} "
                                  f"(diff {abs(live_val - exp_val):.2f} > {tolerance}){Z}")
                            n_failed += 1
                        else:
                            print(f"    {G}✓ {key}: {live_val} (expected {exp_val}){Z}")
            else:
                flat_expected = _flatten_expected(f"{row_key}.{section}", section_expected)
                flat_live = _flatten_live_cell(f"{row_key}.{section}", live_section or {}, set(flat_expected))
                for key, exp_val in flat_expected.items():
                    n_checked += 1
                    live_val = flat_live.get(key)
                    if live_val is None:
                        print(f"    {R}✗ {key}: expected {exp_val}, live is -- (unseeded){Z}")
                        n_failed += 1
                    elif abs(live_val - exp_val) > tolerance:
                        print(f"    {R}✗ {key}: expected {exp_val}, live {live_val} "
                              f"(diff {abs(live_val - exp_val):.2f} > {tolerance}){Z}")
                        n_failed += 1
                    else:
                        print(f"    {G}✓ {key}: {live_val} (expected {exp_val}){Z}")

    print(f"\n  {BD}{n_checked - n_failed}/{n_checked} cells matched within ±{tolerance}{Z}")
    return 1 if n_failed else 0


def monitor_loop() -> None:
    print(f"\n{BD}Live monitor started — Ctrl+C to exit{Z}\n")
    refresh = 5  # seconds

    try:
        while True:
            now_ist = datetime.now(_IST).strftime("%H:%M:%S")
            out: list[str] = []

            out.append(f"{CLS}{BD}{C}PDP Multi-Index Paper Trade Monitor{Z}  "
                       f"{DM}{datetime.now(_IST).strftime('%Y-%m-%d')}  {now_ist} IST{Z}")

            any_data = False
            total_pnl: float = 0.0
            all_pnl_known = True

            for sid in _STRATEGIES:
                label = sid.replace("directional_strangle_", "").upper()
                st = _get("/api/v1/strangle/status", strategy_id=sid)
                out.append("")

                if not st:
                    out.append(f"  {BD}{R}{label}{Z}  {R}not responding{Z}")
                    all_pnl_known = False
                    continue

                any_data = True
                done_val = st.get("done_for_day", False)
                done_str = f"  {R}DONE{Z}" if done_val else f"  {G}live{Z}"
                mode = st.get("mode", "paper")
                day_pnl = st.get("day_pnl")
                if day_pnl is not None:
                    total_pnl += day_pnl
                else:
                    all_pnl_known = False

                # ── Index section header ──────────────────────────────────
                bucket_disp = _fmt_bucket(st.get("bucket"))
                score_disp = _fmt_score(st.get("score"))
                pnl_disp = _fmt_pnl(day_pnl)
                out.append(
                    f"  {BD}{W}{label:<10}{Z}  {bucket_disp}  {score_disp}"
                    f"  │  Day P&L {pnl_disp}{done_str}  {DM}[{mode}]{Z}"
                )
                out.append("  " + "─" * 74)

                legs: list[dict] = st.get("legs", [])
                if not legs:
                    out.append(f"    {DM}no open legs{Z}")
                else:
                    # Sort: shorts first, then hedges, then momentum
                    def _leg_order(lg: dict) -> int:
                        if lg.get("is_momentum"):
                            return 2
                        if lg.get("is_hedge"):
                            return 1
                        return 0

                    for lg in sorted(legs, key=_leg_order):
                        ltype = _leg_type(lg)
                        lopt = _leg_opt(lg)
                        strike = lg.get("strike") or 0
                        lots = lg.get("lots", 0)
                        entry = lg.get("entry_price")
                        ltp = lg.get("ltp")
                        mtm = lg.get("mtm")
                        out.append(
                            f"    {ltype}  {lopt}  {BD}{strike:>8,.0f}{Z}"
                            f"  ×{lots} lots"
                            f"    entry {_fmt_price(entry):>10}"
                            f"    ltp {_fmt_price(ltp):>10}"
                            f"    mtm {_fmt_mtm(mtm):>14}"
                        )

            if not any_data:
                out.append(f"\n  {R}No strategies responding — is `task dev` running?{Z}")
            else:
                out.append("")
                out.append("  " + "━" * 74)
                total_disp = _fmt_pnl(total_pnl) if all_pnl_known else f"{DM}—{Z}"
                out.append(f"  {BD}TOTAL Day P&L{Z}  {total_disp}")

            mon = _get("/api/v1/strangle/monitor", n_events=1)
            out.extend(_indicator_lines(mon))

            out.append("")
            out.append(f"  {DM}Refreshes every {refresh}s  ·  Ctrl+C to exit{Z}")

            print("\n".join(out), end="", flush=True)
            time.sleep(refresh)

    except KeyboardInterrupt:
        print(f"\n\n{DM}Monitor stopped.{Z}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "check":
        pre_checks()

    elif mode == "monitor":
        monitor_loop()

    elif mode == "validate":
        if "--expected" not in sys.argv:
            print("Usage: python scripts/trade_day.py validate --expected path/to/kite_values.json "
                  "[--tolerance N]")
            sys.exit(1)
        expected_path = sys.argv[sys.argv.index("--expected") + 1]
        tolerance = 1.0
        if "--tolerance" in sys.argv:
            tolerance = float(sys.argv[sys.argv.index("--tolerance") + 1])
        mon = _get("/api/v1/strangle/monitor", n_events=1)
        sys.exit(_run_validation(mon, expected_path, tolerance))

    elif mode in ("all", ""):
        ok = pre_checks()
        if not ok:
            print(f"  {Y}Fix warnings above, then run again or use:{Z}")
            print(f"    python scripts/trade_day.py monitor\n")
            sys.exit(1)
        try:
            input(f"  {DM}Press Enter to start live monitor...{Z}\n")
        except (EOFError, KeyboardInterrupt):
            pass
        monitor_loop()

    else:
        print("Usage: python scripts/trade_day.py [check | monitor | validate | all]")
        sys.exit(1)


if __name__ == "__main__":
    main()
