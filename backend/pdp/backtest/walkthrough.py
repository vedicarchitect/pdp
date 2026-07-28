"""Render one trading day as a single self-contained markdown walkthrough.

``render_day(...)`` is pure: it takes already-replayed results and returns a string. All
Mongo access, replaying and file writing lives in ``backtest/walkthrough_run.py``, which
keeps this module unit-testable against synthetic days.

The report is written to be read top-down and abandoned early:

    header -> verdict -> per-strategy narrative -> tables -> minute detail -> FINDINGS

Anyone who only reads the verdict box and the findings list should still learn whether
the day needs attention. The minute-level detail is real (one row per traded minute, not
per decision bar) but folded into ``<details>`` so it never gets in the way.

Output is plain GitHub-flavoured markdown with pipe tables — no dependencies, so nothing
about this can break on a version bump. Wide tables are the reason the minute section is
collapsed rather than trimmed: the whole point is that the evidence is all there when a
finding needs chasing down.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pdp.backtest.sim import DayResult
from pdp.backtest.walkthrough_checks import Finding

__all__ = [
    "LiveOverlay",
    "MarketContext",
    "MinuteRow",
    "Provenance",
    "StrategySection",
    "index_row",
    "render_day",
]

_SEV_ICON = {
    "critical": "🛑", "high": "🔴", "medium": "🟠", "low": "🟡", "info": "🔵",
}


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class MinuteRow:
    """One raw 1-minute bar, with whatever the engine was holding at that minute.

    The engines decide at their own timeframe (5m for the strangle), so most minutes
    carry no decision. They still carry price — which is what you need when a stop or a
    take-profit fired "between" decision bars and the question is what the market
    actually did in between.
    """

    ist_dt: datetime
    open: float
    high: float
    low: float
    close: float
    # (label, strike, ltp) per open leg, e.g. ("PE", 24200.0, 71.2).
    legs: list[tuple[str, float, float | None]] = field(default_factory=list)
    unrealized: float | None = None
    is_decision: bool = False
    action: str = ""


@dataclass(slots=True)
class StrategySection:
    """One strategy's replay of the day."""

    name: str                       # "Directional Strangle"
    config_label: str               # config filename or "<defaults>"
    result: DayResult | None
    findings: list[Finding] = field(default_factory=list)
    # Narrative lines, already formatted by the caller (which knows its own trace type).
    timeline: list[str] = field(default_factory=list)
    # Why nothing happened: reason -> (count, first_hhmm, last_hhmm).
    block_census: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    # Wide per-decision-bar rows: (header, rows) where each row is already stringified.
    bar_table: tuple[list[str], list[list[str]]] | None = None
    minutes: list[MinuteRow] = field(default_factory=list)
    # Set when the strategy did not run at all (no opening range, no chain, ...).
    skipped: str = ""


@dataclass(slots=True)
class MarketContext:
    """The day itself, independent of any strategy."""

    trade_date: date
    underlying: str
    expiry: date | None
    dte: int | None
    lot_size: int
    spot_open: float
    spot_high: float
    spot_low: float
    spot_close: float
    vix_open: float | None = None
    vix_close: float | None = None
    # Loud warnings rendered directly under the title (data gaps, forced runs, ...).
    banners: list[str] = field(default_factory=list)

    @property
    def spot_chg(self) -> float:
        return self.spot_close - self.spot_open

    @property
    def day_type(self) -> str:
        """A coarse label so a month of reports can be skimmed for comparable days."""
        rng = self.spot_high - self.spot_low
        if rng <= 0:
            return "no-range"
        body = abs(self.spot_chg) / rng
        if body >= 0.6:
            return "trend-up" if self.spot_chg > 0 else "trend-down"
        if body <= 0.25:
            return "chop"
        return "mixed"


@dataclass(slots=True)
class Provenance:
    """What produced this file, so a re-run after a fix is meaningfully diffable."""

    generated_at: datetime
    git_sha: str = "unknown"
    configs: dict[str, str] = field(default_factory=dict)  # label -> short hash


@dataclass(slots=True)
class LiveOverlay:
    """Paper/live realised P&L for the same date, when the ledger has it."""

    rows: list[tuple[str, float, int]] = field(default_factory=list)  # (strategy, net, fills)
    note: str = ""


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #


def _num(v: Any, spec: str = "+,.0f", dash: str = "—") -> str:
    if v is None:
        return dash
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """A GitHub pipe table. Empty rows collapse to a single placeholder line."""
    if not rows:
        return ["_(none)_", ""]
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    out.append("")
    return out


def _hhmm(dt: Any) -> str:
    return dt.strftime("%H:%M") if hasattr(dt, "strftime") else str(dt)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #


def _render_header(m: MarketContext, p: Provenance) -> list[str]:
    out = [
        f"# {m.underlying} walkthrough — {m.trade_date:%Y-%m-%d} "
        f"({m.trade_date:%A})",
        "",
    ]
    for b in m.banners:
        out += [f"> ⚠️ **{b}**", ""]
    dte = "—" if m.dte is None else f"{m.dte}d"
    exp = "—" if m.expiry is None else f"{m.expiry:%Y-%m-%d}"
    out += _table(
        ["Open", "High", "Low", "Close", "Change", "Range", "Day type",
         "Expiry", "DTE", "Lot", "VIX"],
        [[
            f"{m.spot_open:,.2f}", f"{m.spot_high:,.2f}", f"{m.spot_low:,.2f}",
            f"{m.spot_close:,.2f}", f"**{m.spot_chg:+,.2f}**",
            f"{m.spot_high - m.spot_low:,.2f}", f"`{m.day_type}`",
            exp, dte, str(m.lot_size),
            f"{_num(m.vix_open, '.2f')} → {_num(m.vix_close, '.2f')}",
        ]],
    )
    cfgs = ", ".join(f"`{k}`@`{v}`" for k, v in sorted(p.configs.items())) or "—"
    out += [
        f"<sub>generated {p.generated_at:%Y-%m-%d %H:%M} IST · git `{p.git_sha}` · "
        f"configs {cfgs}</sub>",
        "",
    ]
    return out


def _render_verdict(sections: list[StrategySection]) -> list[str]:
    rows: list[list[str]] = []
    for s in sections:
        if s.skipped or s.result is None:
            rows.append([f"**{s.name}**", "—", "—", "—", "—", f"_skipped: {s.skipped or 'no result'}_"])
            continue
        r = s.result
        worst = next((f.severity for f in s.findings), "—")
        rows.append([
            f"**{s.name}**",
            f"{r.realized:+,.0f}",
            f"{r.gross_pnl:+,.0f}",
            f"{r.commission:,.0f}",
            str(len(r.trades)),
            (f"{_SEV_ICON.get(worst, '')} {r.done_reason}" if r.done_reason
             else f"{_SEV_ICON.get(worst, '')} {len(s.findings)} finding(s)"
             if s.findings else "clean"),
        ])
    return ["## Verdict", "",
            *_table(["Strategy", "Net", "Gross", "Commission", "Fills", "Status"], rows)]


def _render_trades(r: DayResult) -> list[str]:
    """Every fill, with the index spot beside it — the thing the old walkthrough lacked."""
    rows: list[list[str]] = []
    for t in r.trades:
        rows.append([
            _hhmm(t.bar_time),
            ("**SELL**" if t.side == "SELL" else "BUY"),
            t.opt_type,
            f"{t.strike:,.0f}",
            str(t.qty),
            f"{t.price:,.2f}",
            f"{t.nifty:,.2f}",
            f"{t.avg_entry:,.2f}" if t.avg_entry else "—",
            f"{t.leg_pnl:+,.0f}" if t.leg_pnl else "—",
            f"{t.day_pnl:+,.0f}",
            f"{t.commission_inr:,.0f}",
            f"`{t.note}`",
        ])
    return ["#### Fills", "",
            *_table(["Time", "Side", "Opt", "Strike", "Qty", "Price", "Spot",
                     "Basis", "Leg P&L", "Day P&L", "Comm", "Reason"], rows)]


def _render_legs(r: DayResult) -> list[str]:
    rows: list[list[str]] = []
    for lg in r.leg_records:
        held = ""
        if lg.entry_ist and lg.exit_ist:
            held = f"{int((lg.exit_ist - lg.entry_ist).total_seconds() // 60)}m"
        rows.append([
            lg.opt_type, f"{lg.strike:,.0f}", str(lg.lots),
            _hhmm(lg.entry_ist), f"{lg.avg_entry:,.2f}",
            _hhmm(lg.exit_ist), f"{lg.exit_px:,.2f}",
            held, f"{lg.leg_pnl:+,.0f}", f"`{lg.reason}`",
        ])
    return ["#### Closed legs", "",
            *_table(["Opt", "Strike", "Lots", "In", "Entry", "Out", "Exit",
                     "Held", "P&L", "Reason"], rows)]


def _render_census(section: StrategySection) -> list[str]:
    """Why nothing happened, aggregated — the fastest read on a zero-trade day."""
    if not section.block_census:
        return []
    rows = [[f"`{k}`", str(v[0]), v[1], v[2]]
            for k, v in sorted(section.block_census.items(),
                               key=lambda kv: -kv[1][0])]
    return ["#### Why no trade (bar census)", "",
            *_table(["Reason", "Bars", "First", "Last"], rows)]


def _render_minutes(section: StrategySection) -> list[str]:
    """Per-minute detail, collapsed. Quiet minutes stay; they are the point."""
    if not section.minutes:
        return []
    rows: list[list[str]] = []
    for mr in section.minutes:
        legs = " ".join(
            f"{lbl}{stk:,.0f}@{_num(ltp, '.2f')}" for lbl, stk, ltp in mr.legs
        ) or "flat"
        rows.append([
            ("**" + _hhmm(mr.ist_dt) + "**") if mr.is_decision else _hhmm(mr.ist_dt),
            f"{mr.open:,.2f}", f"{mr.high:,.2f}", f"{mr.low:,.2f}", f"{mr.close:,.2f}",
            legs,
            _num(mr.unrealized),
            f"`{mr.action}`" if mr.action else "",
        ])
    return [
        "<details>",
        f"<summary>Every minute ({len(rows)} rows) — decision bars in bold</summary>",
        "",
        *_table(["Time", "O", "H", "L", "C", "Open legs (LTP)", "Unreal", "Action"], rows),
        "</details>",
        "",
    ]


def _render_section(s: StrategySection) -> list[str]:
    out = [f"## {s.name}", "", f"<sub>config: `{s.config_label}`</sub>", ""]
    if s.skipped or s.result is None:
        out += [f"_Did not run: {s.skipped or 'no result produced'}._", ""]
        return out
    if s.timeline:
        out += ["#### Decision timeline", ""]
        out += [f"- {line}" for line in s.timeline]
        out += [""]
    out += _render_trades(s.result)
    out += _render_legs(s.result)
    out += _render_census(s)
    if s.bar_table is not None:
        headers, rows = s.bar_table
        out += ["<details>",
                f"<summary>Decision bars ({len(rows)} rows) — full indicator state</summary>",
                "",
                *_table(headers, rows),
                "</details>", ""]
    out += _render_minutes(s)
    return out


def _render_contrast(sections: list[StrategySection]) -> list[str]:
    """Two strategies, same minutes. Divergence here is the interesting part."""
    live = [s for s in sections if s.result is not None]
    if len(live) < 2:
        return []
    rows: list[list[str]] = []
    for s in live:
        r = s.result
        assert r is not None
        wins = sum(1 for t in r.trades if (t.leg_pnl or 0.0) > 0)
        losses = sum(1 for t in r.trades if (t.leg_pnl or 0.0) < 0)
        first = _hhmm(r.trades[0].bar_time) if r.trades else "—"
        last = _hhmm(r.trades[-1].bar_time) if r.trades else "—"
        rows.append([s.name, f"{r.realized:+,.0f}", str(len(r.trades)),
                     f"{wins}/{losses}", first, last,
                     r.done_reason or "—"])
    return ["## Cross-strategy contrast", "",
            *_table(["Strategy", "Net", "Fills", "Win/Loss legs", "First fill",
                     "Last fill", "Halt"], rows)]


def _render_live(overlay: LiveOverlay | None) -> list[str]:
    if overlay is None or not overlay.rows:
        return []
    rows = [[name, f"{net:+,.0f}", str(fills)] for name, net, fills in overlay.rows]
    out = ["## Live / paper for the same date", "",
           *_table(["Strategy", "Realised", "Fills"], rows)]
    if overlay.note:
        out += [f"_{overlay.note}_", ""]
    return out


def _render_findings(sections: list[StrategySection]) -> list[str]:
    """The part that makes the report worth running daily."""
    all_findings = [(s.name, f) for s in sections for f in s.findings]
    out = ["## Findings", ""]
    if not all_findings:
        out += ["_No invariant checks tripped. The day looks internally consistent._",
                "",
                "<sub>This says the engine's own books add up — not that the strategy "
                "traded well.</sub>", ""]
        return out
    out += [f"{len(all_findings)} item(s), most severe first. "
            "Fix one, re-run this date, and confirm it clears.", ""]
    for name, f in all_findings:
        out += [f"### {_SEV_ICON.get(f.severity, '')} `{f.id}` — {f.title}",
                "",
                f"**{f.severity.upper()}** · {name}"
                + (f" · bars {', '.join(f.bar_refs)}" if f.bar_refs else ""),
                ""]
        out += [f"- {e}" for e in f.evidence if e]
        out += [""]
    return out


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def render_day(
    market: MarketContext,
    sections: list[StrategySection],
    provenance: Provenance,
    live: LiveOverlay | None = None,
) -> str:
    """Render the whole day as one markdown document."""
    lines: list[str] = []
    lines += _render_header(market, provenance)
    lines += _render_verdict(sections)
    for s in sections:
        lines += _render_section(s)
    lines += _render_contrast(sections)
    lines += _render_live(live)
    lines += _render_findings(sections)
    return "\n".join(lines).rstrip() + "\n"


def index_row(market: MarketContext, sections: list[StrategySection]) -> str:
    """One INDEX.md row for this date, so a month can be skimmed in seconds."""
    nets: list[str] = []
    for s in sections:
        nets.append("—" if s.result is None else f"{s.result.realized:+,.0f}")
    fills = sum(len(s.result.trades) for s in sections if s.result is not None)
    top = [f.id for s in sections for f in s.findings][:3]
    return (
        f"| [{market.trade_date:%Y-%m-%d}]({market.trade_date:%Y-%m-%d}.md) "
        f"| {market.spot_chg:+,.0f} | `{market.day_type}` | "
        + " | ".join(nets)
        + f" | {fills} | {', '.join(f'`{t}`' for t in top) or '—'} |"
    )
