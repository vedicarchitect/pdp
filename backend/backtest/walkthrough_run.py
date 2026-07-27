"""EOD strategy walkthrough — one comprehensive markdown file per trading day.

Replays every strategy over the same day and writes a single self-contained report to
``backend/backtest/manual/<YYYY-MM-DD>.md``: the market context, every decision with the
indicator state behind it, every fill with the index spot beside it, a per-minute price
ribbon, and a ranked FINDINGS list from ``pdp.backtest.walkthrough_checks``.

Built to be run after every close *and* against any historical date, so a bug can be
worked one at a time: read the findings, fix one, re-run the same date, confirm it
cleared. Reports live in git (``backend/backtest/manual/`` is not ignored), so the
before/after diff is the proof.

Mirrors ``intraday_run.py`` deliberately — same quarter-chunked load, same warmup prefix,
same per-date config resolution — so a day rendered here matches what a full run would
have produced for that day.

Usage:
  python backtest/walkthrough_run.py                          # today (the EOD case)
  python backtest/walkthrough_run.py --date 2024-03-14         # any past trading day
  python backtest/walkthrough_run.py --from 2026-07-21 --to 2026-07-24
  python backtest/walkthrough_run.py --days 20 --underlying BANKNIFTY
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import subprocess
import sys
import time as _time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient  # noqa: E402

from backtest.strangle_run import _parse_days, load_pcr_window, load_vix_window  # noqa: E402
from pdp.backtest.commissions import CommissionCalculator  # noqa: E402
from pdp.backtest.day_loader import load_window, warmup_prefix  # noqa: E402
from pdp.backtest.intraday_config import IntradayDirectionalConfig  # noqa: E402
from pdp.backtest.intraday_loader import build_intraday_day  # noqa: E402
from pdp.backtest.intraday_sim import IntradayBarStatus, simulate_intraday_day  # noqa: E402
from pdp.backtest.strangle_config import StrangleConfig, lot_size_for_date  # noqa: E402
from pdp.backtest.strangle_loader import build_strangle_day  # noqa: E402
from pdp.backtest.strangle_sim import BarStatus, simulate_strangle_day  # noqa: E402
from pdp.backtest.walkthrough import (  # noqa: E402
    MarketContext,
    MinuteRow,
    Provenance,
    StrategySection,
    index_row,
    render_day,
)
from pdp.backtest.walkthrough_checks import check_intraday, check_strangle  # noqa: E402
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar  # noqa: E402
from pdp.settings import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("walkthrough")

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "manual"

# NIFTY `option_bars` holds no ingested expiry data across this range, so every day inside
# it silently resolves to a far-side contract. A report over such a day looks authoritative
# and is not. See backend/pdp/backtest/CLAUDE.md.
_NIFTY_BLACKOUT = (date(2020, 12, 3), date(2023, 1, 5))

_IST = timedelta(hours=5, minutes=30)


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
                             capture_output=True, text=True, timeout=5, check=False)
        return out.stdout.strip() or "unknown"
    except Exception:                                     # pragma: no cover - env-dependent
        return "unknown"


def _cfg_hash(cfg_obj) -> str:
    """Short digest of the resolved config, so a re-run after a knob change is visible."""
    return hashlib.sha256(repr(sorted(cfg_obj.to_dict().items())).encode()).hexdigest()[:8]


def _now_ist() -> datetime:
    return (datetime.now(UTC) + _IST).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# Strangle -> report section
# --------------------------------------------------------------------------- #

_STRANGLE_BAR_HEADERS = [
    "Time", "Spot", "Score", "Bucket", "Raw", "Quorum", "Ratio", "Gate",
    "EMA 5m/15m/1h", "ST 5m/15m/1h", "PSAR", "Cam D (S3/R3)", "ORB", "PCR", "VIX",
    "Votes (· = abstained)", "Legs", "Unreal", "Day P&L", "Action",
]


def _fmt(v, spec: str = ".2f", dash: str = "·") -> str:
    if v is None:
        return dash
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


def _ema_dir(e) -> str:
    """One character per timeframe: EMA stack direction, or `·` when unconverged."""
    if e is None or e.ema9 is None or e.ema20 is None:
        return "·"
    return "▲" if e.ema9 > e.ema20 else "▼" if e.ema9 < e.ema20 else "="


def _pair_dir(p) -> str:
    if p is None:
        return "·"
    a, b = p
    return "▲" if a > 0 and b > 0 else "▼" if a < 0 and b < 0 else "="


def _sign(v) -> str:
    return "·" if v is None else "▲" if v > 0 else "▼" if v < 0 else "="


def _strangle_bar_rows(trace: list[BarStatus]) -> list[list[str]]:
    rows: list[list[str]] = []
    for b in trace:
        inp, br = b.bias_inputs, b.bias_result
        votes = "·"
        if br is not None:
            votes = " ".join(
                f"{k}={'·' if vb.abstained else ('+' if vb.vote and vb.vote > 0 else '')}"
                f"{'' if vb.abstained else vb.vote}"
                for k, vb in br.breakdown.items() if vb.weight > 0
            )
        legs = " ".join(
            f"{'H' if lg.is_hedge else 'M' if lg.is_momentum else ''}"
            f"{lg.lots}{lg.opt_type}{lg.strike:.0f}@{_fmt(lg.ltp)}"
            for lg in b.legs
        ) or "flat"
        cam = (f"{inp.cam_daily.s3:.0f}/{inp.cam_daily.r3:.0f}"
               if inp is not None and inp.cam_daily is not None else "·")
        orb = (f"{b.orb_low:.0f}-{b.orb_high:.0f}"
               if b.orb_high is not None and b.orb_low is not None else "·")
        rows.append([
            b.ist_dt.strftime("%H:%M"),
            f"{b.spot:,.2f}",
            f"{b.score:+.3f}",
            b.bucket,
            (br.bucket_raw.value if br is not None and br.bucket_raw.value != b.bucket
             else "="),
            (f"{br.present_weight_frac:.2f}" if br is not None else "·"),
            f"{b.pe_lots}:{b.ce_lots}",
            (br.gate_reason if br is not None else "·"),
            (f"{_ema_dir(inp.ema_5m)}{_ema_dir(inp.ema_15m)}{_ema_dir(inp.ema_1h)}"
             if inp is not None else "·"),
            (f"{_pair_dir(inp.st_5m)}{_pair_dir(inp.st_15m)}{_pair_dir(inp.st_1h)}"
             if inp is not None else "·"),
            (f"{_sign(inp.psar_5m)}{_sign(inp.psar_15m)}{_sign(inp.psar_1h)}"
             if inp is not None else "·"),
            cam,
            orb,
            _fmt(b.pcr),
            _fmt(b.vix_now),
            votes,
            legs,
            f"{b.unrealized:+,.0f}",
            f"{b.day_pnl:+,.0f}",
            f"`{b.action}`" + (" ⛔" if b.done else ""),
        ])
    return rows


def _strangle_timeline(trace: list[BarStatus], decisions: list[dict]) -> list[str]:
    """One line per bar where something happened, with the reasoning behind it."""
    by_time = {b.ist_dt: b for b in trace}
    out: list[str] = []
    for d in decisions:
        b = by_time.get(d["ts_ist"])
        snap = d.get("snapshot", {})
        bits = [f"**{d['ts_ist']:%H:%M}**", f"`{d['event']}`"]
        if d.get("sub_reason"):
            bits.append(f"`{d['sub_reason']}`")
        bits.append(f"— {d.get('action', '')}")
        ctx = []
        if b is not None:
            ctx.append(f"spot {b.spot:,.0f}")
            ctx.append(f"score {b.score:+.3f} {b.bucket}")
            if b.bias_result is not None:
                ctx.append(f"quorum {b.bias_result.present_weight_frac:.2f}")
                if b.bias_result.quorum_forced_neutral:
                    ctx.append("**quorum→neutral**")
                if b.bias_result.extreme_guard_applied:
                    ctx.append("**extreme-guard**")
            ctx.append(f"ratio {b.pe_lots}:{b.ce_lots}")
        if snap.get("leg_pnl") is not None:
            ctx.append(f"leg P&L {snap['leg_pnl']:+,.0f}")
        if snap.get("day_pnl") is not None:
            ctx.append(f"day {snap['day_pnl']:+,.0f}")
        if snap.get("day_loss_halt"):
            ctx.append("**HALT**")
        out.append(" ".join(bits) + (f"  \n  <sub>{' · '.join(ctx)}</sub>" if ctx else ""))
    return out


def _strangle_census(trace: list[BarStatus]) -> dict[str, tuple[int, str, str]]:
    """Aggregate every bar that did not act, by the reason it did not."""
    census: dict[str, list[str]] = {}
    for b in trace:
        if b.action not in ("hold", "", "gated"):
            continue
        br = b.bias_result
        # Ordered by what actually decided the bar. Being positioned outranks the bias
        # read: a bar that holds an open leg was never going to open another one, so
        # attributing it to "neutral" would overstate how often the bias blocked entry.
        if b.done:
            key = "halted"
        elif b.legs:
            key = "already_positioned"
        elif b.gated:
            key = f"vix:{br.gate_reason}" if br is not None else "vix_gated"
        elif b.cooloff:
            key = "stop_cooloff"
        elif br is not None and br.quorum_forced_neutral:
            key = "quorum_below_floor"
        elif b.bucket == "neutral":
            key = "neutral_no_trade"
        else:
            key = f"bucket:{b.bucket}"
        census.setdefault(key, []).append(b.ist_dt.strftime("%H:%M"))
    return {k: (len(v), v[0], v[-1]) for k, v in census.items()}


# --------------------------------------------------------------------------- #
# Intraday -> report section
# --------------------------------------------------------------------------- #

_INTRADAY_BAR_HEADERS = [
    "Time", "Spot", "VWAP", "ORB", "ST 5m/15m", "EMA9/20 5m", "EMA9/20 15m",
    "Opt ST", "Brk", "CamRej", "PE conds", "CE conds", "Block", "Position",
    "LTP", "Unreal", "Day P&L", "Action",
]


def _conds_str(conds: dict[str, bool] | None) -> str:
    if not conds:
        return "·"
    return "".join("✓" if v else "✗" for _k, v in sorted(conds.items()))


def _intraday_bar_rows(trace: list[IntradayBarStatus]) -> list[list[str]]:
    rows: list[list[str]] = []
    for b in trace:
        i = b.inputs
        pos = (f"{b.lots}x{b.side}@{b.strike:.0f} (e{b.avg_entry:.1f})"
               if b.side and b.strike is not None else "flat")
        if b.hedge_strike is not None:
            pos += f" +H{b.hedge_lots}@{b.hedge_strike:.0f}"
        rows.append([
            b.ist_dt.strftime("%H:%M"),
            f"{b.spot:,.2f}",
            _fmt(b.session_vwap),
            (f"{b.orb_low:.0f}-{b.orb_high:.0f}"
             if b.orb_high is not None and b.orb_low is not None else "·"),
            f"{_sign(b.st_dir)}{_sign(i.st_15m_dir) if i is not None else '·'}",
            (f"{_fmt(i.ema9_5m)}/{_fmt(i.ema20_5m)}" if i is not None else "·"),
            (f"{_fmt(i.ema9_15m)}/{_fmt(i.ema20_15m)}" if i is not None else "·"),
            _sign(b.option_st_dir),
            str(b.ema_break_bars),
            str(b.cam_reject_bars),
            _conds_str(b.entry_conditions.get("PE")),
            _conds_str(b.entry_conditions.get("CE")),
            (b.entry_block or "·"),
            pos,
            _fmt(b.ltp),
            f"{b.unrealized:+,.0f}",
            f"{b.day_pnl:+,.0f}",
            f"`{b.action}`" + (f" {b.exit_detail}" if b.exit_detail else ""),
        ])
    return rows


def _intraday_timeline(trace: list[IntradayBarStatus], decisions: list[dict]) -> list[str]:
    by_time = {b.ist_dt: b for b in trace}
    out: list[str] = []
    for d in decisions:
        b = by_time.get(d["ts_ist"])
        bits = [f"**{d['ts_ist']:%H:%M}**", f"`{d['event']}`"]
        if d.get("sub_reason"):
            bits.append(f"`{d['sub_reason']}`")
        bits.append(f"— {d.get('action', '')}")
        ctx = []
        if b is not None:
            ctx.append(f"spot {b.spot:,.0f}")
            if b.session_vwap is not None:
                ctx.append(f"vwap {b.session_vwap:,.0f}")
            ctx.append(f"st {_sign(b.st_dir)}")
            if b.exit_detail:
                ctx.append(b.exit_detail)
            ctx.append(f"day {b.day_pnl:+,.0f}")
        out.append(" ".join(bits) + (f"  \n  <sub>{' · '.join(ctx)}</sub>" if ctx else ""))
    return out


def _intraday_census(trace: list[IntradayBarStatus]) -> dict[str, tuple[int, str, str]]:
    census: dict[str, list[str]] = {}
    for b in trace:
        if b.action != "hold":
            continue
        if b.side:
            # `evaluate_entry` is not even reached while positioned, so there is no block
            # reason to report — say what was actually true instead of "no_evaluation".
            key = "already_positioned"
        elif b.entry_block:
            key = b.entry_block
        elif b.entry_conditions:
            # Name the conditions that failed on *both* sides — the actual blockers.
            failed = sorted({
                k for side in b.entry_conditions.values() for k, v in side.items() if not v
            })
            key = "unmet:" + ",".join(failed) if failed else "unmet"
        else:
            key = "no_evaluation"
        census.setdefault(key, []).append(b.ist_dt.strftime("%H:%M"))
    return {k: (len(v), v[0], v[-1]) for k, v in census.items()}


# --------------------------------------------------------------------------- #
# Per-minute ribbon
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _LegRef:
    label: str
    strike: float
    bars_1m: list


def _minute_rows(
    spot_1m: list,
    chain_1m: dict[tuple[date, str], dict[float, list]],
    trade_date: date,
    leg_windows: list[tuple[datetime, datetime, str, float]],
    decision_times: set[datetime],
    actions: dict[datetime, str],
) -> list[MinuteRow]:
    """Interleave raw 1m spot with each leg's own 1m premium while it was held.

    The engines decide at their configured timeframe (5m for the strangle), so a trace row
    is a 5-minute row. This is what makes the report honour "every minute" without moving
    the decision cadence: it reads the same 1m bars the resampler consumed.
    """
    by_strike: dict[tuple[str, float], list] = {}
    for opt in ("CE", "PE"):
        for stk, bars in chain_1m.get((trade_date, opt), {}).items():
            by_strike[(opt, float(stk))] = bars

    def px_at(bars: list, ts: datetime) -> float | None:
        for b in bars:
            if b[0] == ts:
                return float(b[4])
        return None

    rows: list[MinuteRow] = []
    for ts, o, h, lo, c in spot_1m:
        legs: list[tuple[str, float, float | None]] = []
        for start, end, opt, strike in leg_windows:
            if not (start <= ts <= end):
                continue
            bars = by_strike.get((opt, strike))
            legs.append((opt, strike, px_at(bars, ts) if bars else None))
        rows.append(MinuteRow(
            ist_dt=ts, open=o, high=h, low=lo, close=c, legs=legs,
            is_decision=ts in decision_times, action=actions.get(ts, ""),
        ))
    return rows


def _leg_windows(res) -> list[tuple[datetime, datetime, str, float]]:
    """(entered, exited, opt_type, strike) for every closed leg in the day."""
    return [
        (lg.entry_ist, lg.exit_ist, lg.opt_type, float(lg.strike))
        for lg in res.leg_records if lg.entry_ist and lg.exit_ist
    ]


# --------------------------------------------------------------------------- #
# One day
# --------------------------------------------------------------------------- #


def _build_day(
    d: date,
    window,
    s_cfg: StrangleConfig,
    i_cfg: IntradayDirectionalConfig,
    commission_fn,
    vix_by_day,
    pcr_by_day,
    banners: list[str],
) -> tuple[MarketContext | None, list[StrategySection]]:
    sections: list[StrategySection] = []
    market: MarketContext | None = None

    # Resolve the lot size that was actually in force on this date, exactly as
    # strangle_run/intraday_run do, so an old date is sized the way it really was.
    day_lot = lot_size_for_date(s_cfg.underlying, d)
    s_day_cfg = (s_cfg if day_lot == s_cfg.lot_size
                 else StrangleConfig.from_dict({**s_cfg.to_dict(), "lot_size": day_lot}))
    i_day_cfg = i_cfg.for_date(d)

    # ---- Directional strangle ------------------------------------------- #
    s_day = build_strangle_day(window, s_day_cfg, d,
                               vix_1m_by_day=vix_by_day, pcr_by_day=pcr_by_day)
    s_trace: list[BarStatus] = []
    s_dec: list[dict] = []
    s_res = None
    if s_day is not None:
        s_res = simulate_strangle_day(s_day_cfg, s_day, commission_fn,
                                      trace=s_trace, decisions=s_dec)

    if s_day is not None and s_day.spot_1m:
        highs = [b[2] for b in s_day.spot_1m]
        lows = [b[3] for b in s_day.spot_1m]
        vix = [b.vix_now for b in s_trace if b.vix_now is not None]
        market = MarketContext(
            trade_date=d,
            underlying=s_cfg.underlying,
            expiry=s_day.expiry_date,
            dte=(s_day.expiry_date - d).days if s_day.expiry_date else None,
            lot_size=day_lot,
            spot_open=s_day.spot_1m[0][1], spot_high=max(highs),
            spot_low=min(lows), spot_close=s_day.spot_1m[-1][4],
            vix_open=vix[0] if vix else None, vix_close=vix[-1] if vix else None,
            banners=list(banners),
        )

    s_section = StrategySection(
        name="Directional Strangle",
        config_label=s_cfg.underlying,
        result=s_res,
        skipped="" if s_res is not None else "no decision bars / chain data",
    )
    if s_res is not None:
        s_section.findings = check_strangle(s_day_cfg, s_res, s_trace, s_dec)
        s_section.timeline = _strangle_timeline(s_trace, s_dec)
        s_section.block_census = _strangle_census(s_trace)
        s_section.bar_table = (_STRANGLE_BAR_HEADERS, _strangle_bar_rows(s_trace))
        if s_day is not None:
            s_section.minutes = _minute_rows(
                s_day.spot_1m, window.chain_1m, d, _leg_windows(s_res),
                {b.ist_dt for b in s_trace},
                {b.ist_dt: b.action for b in s_trace if b.action not in ("hold", "")},
            )
    sections.append(s_section)

    # ---- Intraday directional ------------------------------------------- #
    i_day = build_intraday_day(window, i_day_cfg, d)
    i_trace: list[IntradayBarStatus] = []
    i_dec: list[dict] = []
    i_res = None
    skipped = ""
    if i_day is None:
        skipped = "no decision bars / chain data"
    elif i_day.orb_high is None:
        skipped = f"no {i_cfg.orb_start_ist:%H:%M} opening-range candle — entries blocked"
    else:
        i_res = simulate_intraday_day(i_day_cfg, i_day, commission_fn,
                                      trace=i_trace, decisions=i_dec)
        if i_res is None:
            skipped = "engine produced no result"

    i_section = StrategySection(
        name="Intraday Directional",
        config_label=i_cfg.underlying,
        result=i_res,
        skipped=skipped,
    )
    if i_res is not None:
        i_section.findings = check_intraday(i_day_cfg, i_res, i_trace, i_dec)
        i_section.timeline = _intraday_timeline(i_trace, i_dec)
        i_section.block_census = _intraday_census(i_trace)
        i_section.bar_table = (_INTRADAY_BAR_HEADERS, _intraday_bar_rows(i_trace))
    sections.append(i_section)

    return market, sections


# --------------------------------------------------------------------------- #
# INDEX.md
# --------------------------------------------------------------------------- #

_INDEX_HEADER = [
    "# Daily walkthrough index",
    "",
    "One row per generated day, newest last. Open a date for the full report; the",
    "findings column names the top invariant checks that tripped, so a month can be",
    "triaged without opening anything.",
    "",
    "| Date | Chg | Type | Strangle | Intraday | Fills | Top findings |",
    "|---|---|---|---|---|---|---|",
]


def _update_index(out_dir: Path, row: str, trade_date: date) -> None:
    """Insert/replace this date's row, keeping the file sorted by date."""
    path = out_dir / "INDEX.md"
    existing: list[str] = []
    if path.exists():
        existing = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                    if ln.startswith("| [") and f"{trade_date:%Y-%m-%d}" not in ln]
    existing.append(row)
    existing.sort()
    path.write_text("\n".join([*_INDEX_HEADER, *existing, ""]), encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _resolve_days(args) -> list[date]:
    """Any date: an explicit --date, an arbitrary --from/--to range, or --days N."""
    if args.date:
        return [date.fromisoformat(args.date)]
    if not (args.from_date or args.to_date or args.days or args.start):
        # No selector at all -> today, the EOD case.
        return [_now_ist().date()]
    return _parse_days(args)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date", type=str, default=None, metavar="YYYY-MM-DD",
                    help="A single trading day — today's or any past date. "
                         "Defaults to today when no selector is given.")
    ap.add_argument("--from", dest="from_date", type=str, default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", type=str, default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=None, help="N trading days ending at --start")
    ap.add_argument("--start", type=str, default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--underlying", type=str, default=None,
                    choices=["NIFTY", "BANKNIFTY", "SENSEX"])
    ap.add_argument("--strangle-config", type=str, default=None, metavar="PATH")
    ap.add_argument("--intraday-config", type=str, default=None, metavar="PATH")
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--vix-sid", type=str, default="21")
    ap.add_argument("--no-index", action="store_true", help="skip the INDEX.md update")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing report, and allow known-bad data windows")
    args = ap.parse_args()

    days = _resolve_days(args)
    if not days:
        print("No trading days in the requested window.")
        return 1

    s_cfg = (StrangleConfig.from_yaml(args.strangle_config) if args.strangle_config
             else StrangleConfig.from_yaml("backtest/configs/strangle_nifty_hedged.yaml"))
    i_cfg = (IntradayDirectionalConfig.from_yaml(args.intraday_config)
             if args.intraday_config
             else IntradayDirectionalConfig.from_yaml("backtest/configs/intraday_nifty.yaml"))
    if args.underlying:
        s_base = s_cfg.to_dict()
        for k in ("security_id", "strike_step", "lot_size"):
            s_base.pop(k, None)
        s_cfg = StrangleConfig.from_dict({**s_base, "underlying": args.underlying})
        i_base = i_cfg.to_dict()
        for k in ("security_id", "strike_step"):
            i_base.pop(k, None)
        i_cfg = IntradayDirectionalConfig.from_dict({**i_base, "underlying": args.underlying})

    # A historical NIFTY date inside the confirmed ingestion blackout produces a
    # confident-looking report over a mismatched contract. Refuse rather than mislead.
    if s_cfg.underlying == "NIFTY" and not args.force:
        bad = [d for d in days if _NIFTY_BLACKOUT[0] <= d <= _NIFTY_BLACKOUT[1]]
        if bad:
            log.error(
                "%d requested day(s) fall inside the NIFTY option_bars blackout "
                "(%s..%s) — every day in there resolves to a far-side expiry. "
                "Re-run with --force to generate anyway.",
                len(bad), *_NIFTY_BLACKOUT,
            )
            return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    _cal_paths = {
        "NIFTY": s.EXPIRY_CACHE_PATH,
        "BANKNIFTY": s.BANKNIFTY_EXPIRY_CACHE_PATH,
        "SENSEX": s.SENSEX_EXPIRY_CACHE_PATH,
    }
    try:
        cal = NiftyExpiryCalendar.load(_cal_paths.get(s_cfg.underlying, s.EXPIRY_CACHE_PATH))
    except Exception as exc:
        cal = None
        log.warning("expiry calendar unavailable (%s); resolving expiries from option_bars", exc)

    calc = CommissionCalculator(s.backtest_commission)

    def commission_fn(side: str, turnover: float) -> float:
        return float(calc.calculate(side, Decimal(str(turnover))).total_inr)

    prov = Provenance(
        generated_at=_now_ist(),
        git_sha=_git_sha(),
        configs={"strangle": _cfg_hash(s_cfg), "intraday": _cfg_hash(i_cfg)},
    )

    written = 0
    for d in days:
        target = out_dir / f"{d:%Y-%m-%d}.md"
        if target.exists() and not args.force:
            log.info("%s already exists — skipping (use --force to overwrite)", target.name)
            continue

        t0 = _time.perf_counter()
        window = load_window(mdb, cal, [d], security_id=s_cfg.security_id,
                             underlying=s_cfg.underlying,
                             warmup_days=warmup_prefix([d]))
        if d not in window.valid_days:
            log.warning("%s: not a tradeable day (%s) — no report written",
                        d, window.skipped.get(d, "no data"))
            continue

        banners: list[str] = []
        if d in window.cadence_gap_days:
            banners.append(
                "This date resolved to an expiry across a known option_bars ingestion "
                "gap. Every premium below is against a far-side contract — treat the "
                "P&L as unverified."
            )
        vix_by_day = load_vix_window(mdb, args.vix_sid, [d])
        pcr_by_day = load_pcr_window(mdb["option_bars"], window.expiry_by_day, [d],
                                     underlying=s_cfg.underlying)

        market, sections = _build_day(d, window, s_cfg, i_cfg, commission_fn,
                                      vix_by_day, pcr_by_day, banners)
        if market is None:
            log.warning("%s: no spot data — no report written", d)
            continue

        target.write_text(render_day(market, sections, prov), encoding="utf-8")
        if not args.no_index:
            _update_index(out_dir, index_row(market, sections), d)
        written += 1
        n_find = sum(len(s.findings) for s in sections)
        log.info("%s  ->  %s  (%d findings, %.1fs)",
                 d, target.name, n_find, _time.perf_counter() - t0)
        del window

    if not written:
        print("No reports written.")
        return 1
    print(f"\n{written} report(s) in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
