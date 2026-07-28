"""Parameter sweep for the intraday-directional engine.

There is no in-process sweep engine for this strategy (``sweep_engine.py`` is
strangle-only), so this driver shells out to ``backtest/intraday_run.py`` once per
combination and parses the summary line. Runs are ``--no-mongo`` so a 36-combo grid does
not pollute the warehouse with throwaway rows; only the winner is re-run for real.

Usage:
    python scripts/oneoff/intraday_sweep.py --config backtest/configs/intraday_nifty.yaml \
        --from 2025-01-01 --to 2026-07-25
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# backend/scripts/oneoff/intraday_sweep.py -> backend/ (cwd the runner script expects)
_BACKEND = Path(__file__).resolve().parents[2]

# Grid from the approved plan.
GRID: dict[str, list] = {
    "moneyness": [0, -1, -2],
    "unreal_loss_pct": [0.15, 0.20, 0.30],
    "dte_max": [3, 6],
    "hedge_enabled": [True, False],
}

_SUMMARY = re.compile(
    r"Net\s+([+-]?\d+)\s+\|\s+PF\s+([\d.]+|inf)\s+\|\s+Win\s+(\d+)%\s+\|\s+"
    r"MaxDD\s+(\d+)\s+\|\s+Trades\s+(\d+)\s+\|\s+Halted\s+(\d+)"
)


def _flags(combo: dict) -> list[str]:
    out = [
        "--moneyness", str(combo["moneyness"]),
        "--unreal-loss-pct", str(combo["unreal_loss_pct"]),
        "--dte-max", str(combo["dte_max"]),
    ]
    out.append("--hedge" if combo["hedge_enabled"] else "--no-hedge")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--out", default="logs/intraday_sweep.json")
    args = ap.parse_args()

    names = list(GRID)
    combos = [dict(zip(names, vals, strict=True)) for vals in itertools.product(*GRID.values())]
    print(f"{len(combos)} combinations over {args.date_from}..{args.date_to}", flush=True)

    rows: list[dict] = []
    for i, combo in enumerate(combos, 1):
        cmd = [
            sys.executable, "backtest/intraday_run.py",
            "--config-file", args.config,
            "--from", args.date_from, "--to", args.date_to,
            "--no-mongo", *_flags(combo),
        ]
        t0 = time.perf_counter()
        proc = subprocess.run(  # noqa: S603
            cmd, cwd=_BACKEND, capture_output=True, text=True, check=False
        )
        secs = time.perf_counter() - t0
        m = _SUMMARY.search(proc.stdout)
        if m is None:
            print(f"[{i}/{len(combos)}] {combo} -> NO SUMMARY (rc={proc.returncode})",
                  flush=True)
            rows.append({**combo, "error": proc.stderr[-400:] or "no summary line"})
            continue
        net, pf, win, dd, trades, halted = m.groups()
        row = {
            **combo,
            "net": int(net), "pf": float(pf) if pf != "inf" else float("inf"),
            "win_pct": int(win), "max_dd": int(dd), "trades": int(trades),
            "halted": int(halted), "seconds": round(secs, 1),
        }
        rows.append(row)
        print(f"[{i}/{len(combos)}] {combo} -> Net {row['net']:+,} PF {row['pf']} "
              f"DD {row['max_dd']:,} ({secs:.0f}s)", flush=True)

    ok = [r for r in rows if "error" not in r]
    ok.sort(key=lambda r: r["net"], reverse=True)
    out = _BACKEND / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"window": [args.date_from, args.date_to], "grid": GRID, "results": rows},
        indent=2, default=str,
    ), encoding="utf-8")

    print("\n  rank  moneyness  unreal  dte  hedge      net        PF     maxDD   trades")
    print("  " + "-" * 72)
    for rank, r in enumerate(ok[:12], 1):
        print(f"  {rank:>4}  {r['moneyness']:>9}  {r['unreal_loss_pct']:>6}  "
              f"{r['dte_max']:>3}  {r['hedge_enabled']!s:>5}  {r['net']:>+10,}  "
              f"{r['pf']:>6.2f}  {r['max_dd']:>8,}  {r['trades']:>6}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
