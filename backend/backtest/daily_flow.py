"""Generate a human-readable daily flow log from a strangle run's summary.csv.

Usage:
    python backtest/daily_flow.py backtest/runs/strangle_YYYYMMDD-HHMMSS
    python backtest/daily_flow.py backtest/runs/strangle_YYYYMMDD-HHMMSS --year 2024
    python backtest/daily_flow.py backtest/runs/strangle_YYYYMMDD-HHMMSS --monthly
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def _sign(v: float) -> str:
    return "+" if v >= 0 else ""


def _bar(v: float, scale: float = 50000.0, width: int = 20) -> str:
    n = max(0, min(width, int(abs(v) / scale * width)))
    return ("+" * n).ljust(width) if v >= 0 else ("-" * n).rjust(width)


def _fmt(v: float) -> str:
    return f"{_sign(v)}{v:,.0f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", help="Path to a backtest run directory")
    ap.add_argument("--year", type=int, default=None, help="Filter to a specific year")
    ap.add_argument("--monthly", action="store_true", help="Show monthly roll-up instead of daily")
    ap.add_argument("--losing", action="store_true", help="Show only losing days")
    ap.add_argument("--halted", action="store_true", help="Show only halted days")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    csv_path = run_dir / "summary.csv"
    if not csv_path.exists():
        print(f"summary.csv not found in {run_dir}", file=sys.stderr)
        return 1

    rows = []
    with csv_path.open() as f:
        for r in csv.DictReader(f):
            rows.append(r)

    if args.year:
        rows = [r for r in rows if r["date"].startswith(str(args.year))]
    if args.losing:
        rows = [r for r in rows if float(r["net"]) < 0]
    if args.halted:
        rows = [r for r in rows if r["halted"]]

    manifest = run_dir / "manifest.json"
    run_label = run_dir.name
    try:
        import json
        m = json.loads(manifest.read_text())
        cfg = m.get("config", {})
        run_label = (
            f"hedge={'ON' if cfg.get('hedge_enabled') else 'OFF'}  "
            f"scale_lots={cfg.get('scale_lots', 1)}  "
            f"neutral={'3:3' if not cfg.get('neutral_no_trade', True) else 'skip'}  "
            f"tp={int(cfg.get('take_profit_pct', 0.5) * 100)}%  "
            f"dll=Rs{cfg.get('day_loss_limit', 15000):,.0f}"
        )
    except Exception:  # noqa: S110
        pass

    if args.monthly:
        _print_monthly(rows, run_label)
    else:
        _print_daily(rows, run_label)
    return 0


def _print_daily(rows: list[dict], label: str) -> None:
    sep = "=" * 120
    print(f"\n{sep}")
    print(f"  DAILY FLOW  â€”  {label}")
    print(f"  {len(rows)} days shown")
    print(sep)
    hdr = (
        f"  {'Date':<12}  {'NIFTY':>8}  {'Trades':>6}  {'Gross':>11}"
        f"  {'Comm':>7}  {'Net':>11}  {'Cum Equity':>12}  {'DrawDown':>9}  Bar (±50k/block)"
    )
    print(hdr)
    print(f"  {'-'*12}  {'-'*8}  {'-'*6}  {'-'*11}  {'-'*7}  {'-'*11}  {'-'*12}  {'-'*9}  {'-'*20}")
    for r in rows:
        net = float(r["net"])
        cum = float(r["cum_equity"])
        dd = float(r["drawdown"])
        chg = float(r["nifty_chg"])
        trades = int(r["trades"])
        gross = float(r["gross_pnl"])
        comm = float(r["commission"])
        halt = f"  â—¼ HALT({r['halted']})" if r["halted"] else ""
        bar = _bar(net)
        print(
            f"  {r['date']:<12}  {chg:>+8.1f}  {trades:>6}  {gross:>+11,.0f}  {comm:>7,.0f}  "
            f"{net:>+11,.0f}  {cum:>+12,.0f}  {dd:>9,.0f}  {bar}{halt}"
        )
    # totals
    total_net = sum(float(r["net"]) for r in rows)
    total_gross = sum(float(r["gross_pnl"]) for r in rows)
    total_comm = sum(float(r["commission"]) for r in rows)
    total_trades = sum(int(r["trades"]) for r in rows)
    print(f"  {'â”€'*118}")
    print(
        f"  {'TOTAL':<12}  {'':>8}  {total_trades:>6}"
        f"  {total_gross:>+11,.0f}  {total_comm:>7,.0f}  {total_net:>+11,.0f}"
    )
    print(f"{'='*120}\n")


def _print_monthly(rows: list[dict], label: str) -> None:
    from collections import defaultdict
    months: dict[str, dict] = defaultdict(
        lambda: {"net": 0.0, "gross": 0.0, "comm": 0.0, "trades": 0, "days": 0, "wins": 0, "halts": 0, "max_dd": 0.0}  # noqa: E501
    )
    for r in rows:
        ym = r["date"][:7]
        m = months[ym]
        net = float(r["net"])
        m["net"] += net
        m["gross"] += float(r["gross_pnl"])
        m["comm"] += float(r["commission"])
        m["trades"] += int(r["trades"])
        m["days"] += 1
        if net >= 0:
            m["wins"] += 1
        if r["halted"]:
            m["halts"] += 1
        m["max_dd"] = max(m["max_dd"], float(r["drawdown"]))

    sep = "=" * 110
    print(f"\n{sep}")
    print(f"  MONTHLY FLOW  â€”  {label}")
    print(sep)
    print(
        f"  {'Month':<8}  {'Days':>4}  {'Trades':>6}  {'Gross':>11}"
        f"  {'Comm':>7}  {'Net':>11}  {'Win%':>5}  {'MaxDD':>9}  {'Halt':>4}  Bar (±2L/block)"
    )
    print(f"  {'-'*8}  {'-'*4}  {'-'*6}  {'-'*11}  {'-'*7}  {'-'*11}  {'-'*5}  {'-'*9}  {'-'*4}  {'-'*20}")
    cum = 0.0
    for ym in sorted(months):
        m = months[ym]
        net = m["net"]
        cum += net
        win_pct = m["wins"] / m["days"] * 100 if m["days"] else 0
        bar = _bar(net, scale=200_000)
        halt_str = str(m["halts"]) if m["halts"] else ""
        flag = "*" if m["halts"] else " "
        print(
            f"  {ym:<8}  {m['days']:>4}  {m['trades']:>6}  {m['gross']:>+11,.0f}  {m['comm']:>7,.0f}  "
            f"{net:>+11,.0f}  {win_pct:>4.0f}%  {m['max_dd']:>9,.0f}  {flag}{halt_str:>3}  {bar}"
        )
    total_net = sum(months[ym]["net"] for ym in months)
    total_comm = sum(months[ym]["comm"] for ym in months)
    total_trades = sum(months[ym]["trades"] for ym in months)
    total_gross = sum(months[ym]["gross"] for ym in months)
    print(f"  {'â”€'*108}")
    print(
        f"  {'TOTAL':<8}  {'':>4}  {total_trades:>6}"
        f"  {total_gross:>+11,.0f}  {total_comm:>7,.0f}  {total_net:>+11,.0f}"
    )
    print(f"{'='*110}\n")


if __name__ == "__main__":
    raise SystemExit(main())

