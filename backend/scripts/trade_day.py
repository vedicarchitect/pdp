"""
trade_day.py — Pre-market checks + live monitoring dashboard for 3-index paper trading.

Usage (run from backend/ directory):
    python scripts/trade_day.py            # pre-checks → live monitor
    python scripts/trade_day.py check      # pre-checks only, then exit
    python scripts/trade_day.py monitor    # live monitor only (API must be running)

Endpoints used:
    GET /healthz                              API alive
    GET /readyz                               DB / Redis / Mongo health
    GET /api/v1/strategies                    strategy list + status
    GET /api/v1/strangle/status?strategy_id=  per-strategy state
    GET /api/v1/instruments?underlying=X&limit=1  instruments check
    http://localhost:9200/                    OpenSearch health
    http://localhost:5601/                    OpenSearch Dashboards
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
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
    if isinstance(strats_raw, list):
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


def monitor_loop() -> None:
    print(f"\n{BD}Live monitor started — Ctrl+C to exit{Z}\n")
    prev_lines = 0
    refresh = 5  # seconds

    try:
        while True:
            now_ist = datetime.now(_IST).strftime("%H:%M:%S")
            out: list[str] = []

            out.append(f"{CLS}{BD}{C}PDP Multi-Index Paper Trade Monitor{Z}  "
                       f"{DM}{datetime.now(_IST).strftime('%Y-%m-%d')}  {now_ist} IST{Z}")
            out.append("")

            # Header row
            out.append(
                f"  {BD}{'Index':<12}  {'Bucket':<17}  {'Score':>7}  "
                f"{'Shorts':>6}  {'Hedges':>6}  {'Day P&L':>12}  {'Done':<5}  {'Status'}{Z}"
            )
            out.append("  " + "─" * 82)

            any_data = False
            for sid in _STRATEGIES:
                label = sid.replace("directional_strangle_", "").upper()
                st = _get("/api/v1/strangle/status", strategy_id=sid)
                if st:
                    any_data = True
                    done_val = st.get("done_for_day", False)
                    done_str = f"{R}DONE{Z}" if done_val else f"{G}live{Z}"
                    mode = st.get("mode", "paper")
                    out.append(
                        f"  {BD}{label:<12}{Z}  {_fmt_bucket(st.get('bucket')):<26}  "
                        f"{_fmt_score(st.get('score')):>16}  "
                        f"{st.get('n_open_shorts', 0):>6}  "
                        f"{st.get('n_open_hedges', 0):>6}  "
                        f"{_fmt_pnl(st.get('day_pnl')):>21}  "
                        f"{done_str}  [{DM}{mode}{Z}]"
                    )
                else:
                    out.append(f"  {BD}{label:<12}{Z}  {R}not responding{Z}")

            if not any_data:
                out.append(f"\n  {R}No strategies responding — is `task dev` running?{Z}")

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
        print(f"Usage: python scripts/trade_day.py [check | monitor | all]")
        sys.exit(1)


if __name__ == "__main__":
    main()
