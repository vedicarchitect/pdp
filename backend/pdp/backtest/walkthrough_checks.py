"""Automated invariant checks over one replayed trading day.

A 375-minute dump is not something anyone reads daily. The EOD walkthrough is only
useful if it *says what looks wrong*, so every report ends in a ranked FINDINGS list
produced here. Each detector below exists because the defect it catches was real:

* ``F-AVG-DRIFT`` generalises the ``close_partial_leg`` entry-price doubling — a leg's
  average entry moving with no fill behind it is always a bug, whatever caused it.
* ``F-STRADDLE`` catches the ``premium_floor`` → ATM collapse that quietly turned a
  2026-07-21 strangle into a straddle.
* ``F-STOP-RESET`` catches a rollup re-basing an underwater leg's stop.
* ``F-VIX-ACTIVE`` is the regression guard for the single-source VIX gate.

Detectors are **pure** over ``(config, DayResult, trace, decisions)`` — no I/O — so each
is unit-testable with a synthetic day, and every one has both a positive and a negative
fixture so it cannot silently stop firing.

Findings are advisory. A finding is not proof of a bug; it is a place to look, ordered so
the most consequential place is first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pdp.backtest.intraday_config import IntradayDirectionalConfig
from pdp.backtest.intraday_sim import IntradayBarStatus
from pdp.backtest.sim import DayResult
from pdp.backtest.strangle_config import StrangleConfig
from pdp.backtest.strangle_sim import BarStatus

__all__ = ["SEVERITIES", "Finding", "check_intraday", "check_strangle", "rank"]

# Most consequential first. Used for ordering and for the INDEX.md summary.
SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

# Tunables. Deliberately loose — a detector that cries wolf gets ignored, which is worse
# than one that misses an edge case.
# Take-profit fires on the first *decision bar* where capture crosses the target, so a
# premium that gapped inside the bar legitimately overshoots. Only a big overshoot
# suggests the basis was wrong; anything under this is bar discretisation, not a bug.
_TP_OVERSHOOT = 0.20
_TP_UNDERSHOOT = 0.02         # firing *below* target is never discretisation
_STALE_BARS = 12              # consecutive identical LTPs that look like a data gap
_FLAT_MOVE_POINTS = 100.0     # |spot change| that makes a zero-trade day worth noting
_MTM_TOLERANCE = 1.0          # rupees
_PRICE_SRC_POINTS = 1.0       # index points of spot disagreement worth reporting


@dataclass(slots=True)
class Finding:
    """One thing worth looking at, with the evidence needed to act on it."""

    id: str
    severity: str
    title: str
    evidence: list[str] = field(default_factory=list)
    bar_refs: list[str] = field(default_factory=list)  # "10:30", "14:05", ...

    def __post_init__(self) -> None:
        if self.severity not in _SEV_RANK:
            raise ValueError(f"unknown severity {self.severity!r}; expected one of {SEVERITIES}")


def rank(findings: list[Finding]) -> list[Finding]:
    """Most severe first; stable within a severity so detector order is preserved."""
    return sorted(findings, key=lambda f: _SEV_RANK[f.severity])


def _hhmm(dt: Any) -> str:
    return dt.strftime("%H:%M") if hasattr(dt, "strftime") else str(dt)


def _opens_risk(t: Any) -> bool:
    """True for a fill that *opens* a short — an entry, re-entry, scale-in or roll.

    ``side == "SELL"`` is not enough: closing a protective long hedge is also a SELL, and
    counting those as new positions makes the halt detectors fire on every square-off.
    The structural distinction is that an opening fill has realised nothing yet
    (``leg_pnl is None``) and leaves lots on the book (``cum_lots > 0``).
    """
    return t.side == "SELL" and t.leg_pnl is None and t.cum_lots > 0


# --------------------------------------------------------------------------- #
# Shared detectors (both engines produce the same DayResult/Trade/LegRecord)
# --------------------------------------------------------------------------- #


def _check_pnl_reconciles(res: DayResult) -> list[Finding]:
    """The day's headline numbers must add up from the fills that produced them."""
    out: list[Finding] = []
    # `Trade.leg_pnl` is None on an opening fill (nothing realised yet) — only closes
    # carry a value, and it is their sum that has to equal the day's gross.
    legs_sum = sum((t.leg_pnl or 0.0) for t in res.trades)
    if abs(legs_sum - res.gross_pnl) > _MTM_TOLERANCE:
        out.append(Finding(
            id="F-PNL-RECON", severity="critical",
            title="Sum of per-fill leg P&L does not equal the day's gross P&L",
            evidence=[f"sum(trade.leg_pnl) = {legs_sum:+.2f}",
                      f"DayResult.gross_pnl = {res.gross_pnl:+.2f}",
                      f"difference = {legs_sum - res.gross_pnl:+.2f}"],
        ))
    comm_sum = sum(t.commission_inr for t in res.trades)
    if abs((res.gross_pnl - comm_sum) - res.realized) > _MTM_TOLERANCE:
        out.append(Finding(
            id="F-PNL-RECON", severity="critical",
            title="realized != gross_pnl - commission",
            evidence=[f"gross {res.gross_pnl:+.2f} - commission {comm_sum:.2f} "
                      f"= {res.gross_pnl - comm_sum:+.2f}",
                      f"DayResult.realized = {res.realized:+.2f}"],
        ))
    return out


def _check_flat_on_a_move(res: DayResult, label: str) -> list[Finding]:
    """Standing aside is a decision too — but on a big directional day, say so."""
    if res.trades or abs(res.nifty_chg) < _FLAT_MOVE_POINTS:
        return []
    return [Finding(
        id="F-FLAT-MOVE", severity="info",
        title=f"{label} took zero trades on a {res.nifty_chg:+.0f} point day",
        evidence=[f"spot {res.nifty_open:.1f} -> {res.nifty_close:.1f} "
                  f"({res.nifty_chg:+.1f})",
                  "Check the why-no-trade census above for the blocking reason."],
    )]


def _check_stale_ltp(rows: list[tuple[Any, str, float]]) -> list[Finding]:
    """A premium that does not move for many consecutive bars is usually missing data.

    ``rows`` is ``(ist_dt, leg_key, ltp)`` for every priced open leg, in bar order.
    A flat LTP reads as a calm market in every downstream number — P&L, stops,
    take-profit — so a gap here silently corrupts the whole day rather than erroring.
    """
    runs: dict[str, tuple[float, list[Any]]] = {}
    out: list[Finding] = []
    flagged: set[str] = set()
    for ist_dt, key, ltp in rows:
        prev = runs.get(key)
        if prev is not None and prev[0] == ltp:
            prev[1].append(ist_dt)
        else:
            runs[key] = (ltp, [ist_dt])
            continue
        stamps = runs[key][1]
        if len(stamps) >= _STALE_BARS and key not in flagged:
            flagged.add(key)
            out.append(Finding(
                id="F-STALE-BAR", severity="medium",
                title=f"{key} premium unchanged for {len(stamps)}+ consecutive bars",
                evidence=[f"price stuck at {ltp:.2f} from {_hhmm(stamps[0])}",
                          "Likely a missing/forward-filled option bar, not a calm market."],
                bar_refs=[_hhmm(stamps[0]), _hhmm(stamps[-1])],
            ))
    return out


# --------------------------------------------------------------------------- #
# Directional strangle
# --------------------------------------------------------------------------- #


def check_strangle(
    cfg: StrangleConfig,
    res: DayResult,
    trace: list[BarStatus],
    decisions: list[dict[str, Any]],
) -> list[Finding]:
    """Run every strangle detector and return the findings, most severe first."""
    out: list[Finding] = []
    out += _check_pnl_reconciles(res)
    out += _check_flat_on_a_move(res, "Strangle")
    out += _strangle_avg_entry_drift(res, trace)
    out += _strangle_mtm_consistency(cfg, trace)
    out += _strangle_halt_breach(cfg, res, trace)
    out += _strangle_take_profit_math(cfg, res)
    out += _strangle_roll_rebased_a_loss(res, decisions)
    out += _strangle_straddle(trace)
    out += _strangle_roll_inward(decisions, trace)
    out += _strangle_squareoff_price_source(res, trace)
    out += _strangle_quorum(cfg, res, trace)
    out += _strangle_vix_gate_active(cfg, trace)
    out += _strangle_missing_hedge(cfg, trace)
    out += _check_stale_ltp([
        (b.ist_dt, f"{lg.opt_type} {lg.strike:.0f}", lg.ltp)
        for b in trace for lg in b.legs if lg.ltp is not None and not lg.is_hedge
    ])
    return rank(out)


def _strangle_avg_entry_drift(res: DayResult, trace: list[BarStatus]) -> list[Finding]:
    """A leg's average entry may only move on a fill.

    ``Leg.avg_entry`` is derived (``total_cost / total_qty``), so any code that writes
    one of those without the other silently re-bases the position — and every stop,
    take-profit and P&L figure computed afterwards is wrong by that factor. This is the
    generic form of the 2026-07-21 ``close_partial_leg`` bug: it fires on that specific
    defect and on any future one with the same shape.
    """
    fill_minutes = {(t.bar_time.replace(second=0, microsecond=0), t.opt_type)
                    for t in res.trades}
    last: dict[str, tuple[float, Any]] = {}
    out: list[Finding] = []
    for b in trace:
        for lg in b.legs:
            if lg.is_hedge or lg.is_momentum:
                continue
            key = f"{lg.opt_type} {lg.strike:.0f}"
            prev = last.get(key)
            last[key] = (lg.avg_entry, b.ist_dt)
            if prev is None or abs(prev[0] - lg.avg_entry) < 0.005:
                continue
            minute = b.ist_dt.replace(second=0, microsecond=0)
            if (minute, lg.opt_type) in fill_minutes:
                continue  # a real fill moved the average — expected
            out.append(Finding(
                id="F-AVG-DRIFT", severity="critical",
                title=f"{key} average entry changed with no fill behind it",
                evidence=[f"{_hhmm(prev[1])} avg_entry {prev[0]:.2f}",
                          f"{_hhmm(b.ist_dt)} avg_entry {lg.avg_entry:.2f} "
                          f"(x{lg.avg_entry / prev[0]:.3f})" if prev[0] else "",
                          "No trade was recorded on this leg at that minute."],
                bar_refs=[_hhmm(b.ist_dt)],
            ))
    return out


def _strangle_mtm_consistency(cfg: StrangleConfig, trace: list[BarStatus]) -> list[Finding]:
    """MTM must equal (avg_entry - ltp) x lots x lot_size for a short leg.

    Catches a qty/cost pair that has gone out of step with the lots the report shows.
    """
    for b in trace:
        for lg in b.legs:
            if lg.ltp is None or lg.mtm is None or lg.is_hedge or lg.is_momentum:
                continue
            expected = (lg.avg_entry - lg.ltp) * lg.lots * cfg.lot_size
            if abs(expected - lg.mtm) > _MTM_TOLERANCE:
                return [Finding(
                    id="F-MTM-RECON", severity="critical",
                    title=f"{lg.opt_type} {lg.strike:.0f} MTM disagrees with its own lots",
                    evidence=[f"{_hhmm(b.ist_dt)} lots={lg.lots} avg_entry={lg.avg_entry:.2f} "
                              f"ltp={lg.ltp:.2f}",
                              f"expected MTM {expected:+.2f}, engine reports {lg.mtm:+.2f}",
                              "total_qty and total_cost have gone out of step."],
                    bar_refs=[_hhmm(b.ist_dt)],
                )]
    return []


def _strangle_halt_breach(
    cfg: StrangleConfig, res: DayResult, trace: list[BarStatus],
) -> list[Finding]:
    """Once the day-loss cap is breached, the engine must stop opening risk."""
    out: list[Finding] = []
    for b in trace:
        if b.day_pnl <= -cfg.day_loss_limit and not b.done:
            out.append(Finding(
                id="F-HALT-BREACH", severity="high",
                title="Day-loss cap breached but the engine had not halted",
                evidence=[f"{_hhmm(b.ist_dt)} day_pnl {b.day_pnl:+.0f} "
                          f"vs cap {-cfg.day_loss_limit:+.0f}",
                          f"bar action: {b.action}"],
                bar_refs=[_hhmm(b.ist_dt)],
            ))
            break
    halted_at = next((b.ist_dt for b in trace if b.done), None)
    if halted_at is not None:
        late = [t for t in res.trades if _opens_risk(t) and t.bar_time > halted_at]
        if late:
            out.append(Finding(
                id="F-HALT-BREACH", severity="high",
                title=f"{len(late)} new position(s) opened after the day halted",
                evidence=[f"halt at {_hhmm(halted_at)}"] +
                         [f"{_hhmm(t.bar_time)} SELL {t.opt_type} {t.strike:.0f} "
                          f"qty {t.qty}" for t in late[:5]],
                bar_refs=[_hhmm(t.bar_time) for t in late[:5]],
            ))
    return out


def _strangle_take_profit_math(cfg: StrangleConfig, res: DayResult) -> list[Finding]:
    """A take-profit exit should have captured roughly the configured fraction.

    The rule fires on the first decision bar whose capture crosses the target, so a
    premium that moved inside the bar legitimately overshoots — that is discretisation,
    not a defect, and flagging it would train the reader to ignore this finding. Two
    things are *not* discretisation:

    * firing **below** target — the trigger compared against something other than the
      real credit;
    * a very large overshoot — which is what an inflated ``avg_entry`` produces.
    """
    out: list[Finding] = []
    for t in res.trades:
        if t.note != "take_profit" or t.avg_entry <= 0:
            continue
        captured = (t.avg_entry - t.price) / t.avg_entry
        delta = captured - cfg.take_profit_pct
        if not (delta < -_TP_UNDERSHOOT or delta > _TP_OVERSHOOT):
            continue
        out.append(Finding(
            id="F-TP-MATH", severity="high",
            title=f"{t.opt_type} {t.strike:.0f} take-profit captured "
                  f"{captured * 100:.1f}% (target {cfg.take_profit_pct * 100:.0f}%)",
            evidence=[f"{_hhmm(t.bar_time)} entry {t.avg_entry:.2f} -> "
                      f"exit {t.price:.2f}, leg P&L {(t.leg_pnl or 0.0):+.0f}",
                      ("Fired below target — the trigger did not compare against the "
                       "real credit." if delta < 0 else
                       "An overshoot this large usually means the basis is wrong, not "
                       "that the market gapped between bars.")],
            bar_refs=[_hhmm(t.bar_time)],
        ))
    return out


def _strangle_roll_rebased_a_loss(res: DayResult, decisions: list[dict[str, Any]]) -> list[Finding]:
    """A rollup that closes a losing leg resets its stop basis to the new premium.

    The loss is realised and the replacement leg starts fresh, so the position can
    keep giving back the same percentage repeatedly without any single stop looking
    unusual. Worth seeing explicitly rather than inferring from the P&L curve.
    """
    out: list[Finding] = []
    for t in res.trades:
        if t.note == "roll" and t.side == "BUY" and (t.leg_pnl or 0.0) < 0:
            out.append(Finding(
                id="F-STOP-RESET", severity="high",
                title=f"{t.opt_type} {t.strike:.0f} rolled while underwater "
                      f"({(t.leg_pnl or 0.0):+.0f}) — stop basis reset",
                evidence=[f"{_hhmm(t.bar_time)} closed at {t.price:.2f} "
                          f"from basis {t.avg_entry:.2f}",
                          "The replacement leg is stopped against its own (lower) "
                          "premium, not the original credit."],
                bar_refs=[_hhmm(t.bar_time)],
            ))
    return out


def _strangle_straddle(trace: list[BarStatus]) -> list[Finding]:
    """PE and CE short at the same strike is a straddle, not a strangle.

    Happens when ``premium_floor`` leaves nothing above the floor except ATM — common on
    expiry day, where it silently doubles gamma exposure versus what the config implies.
    """
    for b in trace:
        shorts = [lg for lg in b.legs if not lg.is_hedge and not lg.is_momentum]
        pe = next((lg for lg in shorts if lg.opt_type == "PE"), None)
        ce = next((lg for lg in shorts if lg.opt_type == "CE"), None)
        if pe is not None and ce is not None and pe.strike == ce.strike:
            return [Finding(
                id="F-STRADDLE", severity="medium",
                title=f"Both sides sold at the same strike ({pe.strike:.0f}) — "
                      f"this is a straddle",
                evidence=[f"first seen {_hhmm(b.ist_dt)}: "
                          f"{pe.lots} PE + {ce.lots} CE @ {pe.strike:.0f}",
                          "Usually premium_floor leaving only ATM above the floor."],
                bar_refs=[_hhmm(b.ist_dt)],
            )]
    return []


def _strangle_roll_inward(decisions: list[dict[str, Any]], trace: list[BarStatus]) -> list[Finding]:
    """A rollup should move away from spot, not toward it."""
    spot_at = {b.ist_dt: b.spot for b in trace}
    out: list[Finding] = []
    for d in decisions:
        if d.get("event") != "rollup":
            continue
        snap = d.get("snapshot", {})
        frm, to = snap.get("from_strike"), snap.get("to_strike")
        spot = spot_at.get(d["ts_ist"], snap.get("spot"))
        if frm is None or to is None or spot is None:
            continue
        if abs(to - spot) < abs(frm - spot):
            out.append(Finding(
                id="F-ROLL-INWARD", severity="medium",
                title=f"Roll moved {snap.get('opt_type', '?')} toward spot "
                      f"({frm:.0f} -> {to:.0f}, spot {spot:.0f})",
                evidence=[f"{_hhmm(d['ts_ist'])} distance from spot "
                          f"{abs(frm - spot):.0f} -> {abs(to - spot):.0f}",
                          "The replacement sits closer to the money than the leg it "
                          "replaced, increasing risk on a decayed position."],
                bar_refs=[_hhmm(d["ts_ist"])],
            ))
    return out


def _strangle_squareoff_price_source(res: DayResult, trace: list[BarStatus]) -> list[Finding]:
    """Every exit should reference the same bar field.

    The end-of-day square-off prices spot off the bar's *open* while every other exit
    uses its close, so the fill's recorded spot disagrees with the decision spot for the
    same minute. On a quiet closing bar that is a rounding-scale difference and not worth
    anyone's attention; it is reported only once the gap is large enough to change how
    the trade table reads against the minute table.
    """
    spot_at = {b.ist_dt: b.spot for b in trace}
    for t in res.trades:
        if not t.note.startswith("squareoff"):
            continue
        decision_spot = spot_at.get(t.bar_time)
        if decision_spot is None or abs(decision_spot - t.nifty) < _PRICE_SRC_POINTS:
            continue
        return [Finding(
            id="F-PRICE-SRC", severity="medium",
            title="Square-off fills record a different spot than the decision bar",
            evidence=[f"{_hhmm(t.bar_time)} fill spot {t.nifty:.2f} vs "
                      f"decision-bar spot {decision_spot:.2f} "
                      f"(diff {t.nifty - decision_spot:+.2f})",
                      "Square-off prices off the bar open; every other exit uses close."],
            bar_refs=[_hhmm(t.bar_time)],
        )]
    return []


def _strangle_quorum(
    cfg: StrangleConfig, res: DayResult, trace: list[BarStatus],
) -> list[Finding]:
    """Report entries taken on a thin vote set, and inputs that abstained all day."""
    out: list[Finding] = []
    entry_minutes = {t.bar_time for t in res.trades if _opens_risk(t)}
    thin = [b for b in trace
            if b.ist_dt in entry_minutes and b.bias_result is not None
            and b.bias_result.present_weight_frac < cfg.weights.min_quorum_weight_frac]
    if thin:
        out.append(Finding(
            id="F-QUORUM", severity="low",
            title=f"{len(thin)} entry bar(s) below the quorum floor",
            evidence=[f"{_hhmm(b.ist_dt)} quorum "
                      f"{b.bias_result.present_weight_frac:.2f} < "
                      f"{cfg.weights.min_quorum_weight_frac:.2f}"
                      for b in thin[:5] if b.bias_result is not None],
            bar_refs=[_hhmm(b.ist_dt) for b in thin[:5]],
        ))
    # An input weighted above zero that abstained on every single bar is dead weight —
    # it silently biases the renormalised score toward whatever the others said.
    with_bias = [b for b in trace if b.bias_result is not None]
    if with_bias:
        names = set(with_bias[0].bias_result.breakdown)  # type: ignore[union-attr]
        dead = sorted(
            n for n in names
            if all(b.bias_result.breakdown[n].abstained for b in with_bias)  # type: ignore[union-attr]
            and with_bias[0].bias_result.breakdown[n].weight > 0  # type: ignore[union-attr]
        )
        if dead:
            out.append(Finding(
                id="F-DEAD-INPUT", severity="high",
                title=f"{len(dead)} weighted bias input(s) abstained on every bar",
                evidence=[f"never voted: {', '.join(dead)}",
                          "A weighted input that never votes is indistinguishable, from "
                          "the score, from a genuinely neutral market."],
            ))
    return out


def _strangle_vix_gate_active(cfg: StrangleConfig, trace: list[BarStatus]) -> list[Finding]:
    """Regression guard for the single-source VIX gate.

    The gate has exactly one switch (``weights.vix_gate_enabled``). If a bar reports a
    gate verdict other than ``vix_gate_disabled`` while the config says it is off, a
    caller has reintroduced its own copy of the switch.
    """
    if cfg.weights.vix_gate_enabled:
        return []
    for b in trace:
        br = b.bias_result
        if br is not None and br.gate_reason and br.gate_reason != "vix_gate_disabled":
            return [Finding(
                id="F-VIX-ACTIVE", severity="low",
                title="VIX gate evaluated despite weights.vix_gate_enabled = false",
                evidence=[f"{_hhmm(b.ist_dt)} gate_reason={br.gate_reason!r} "
                          f"gated={br.gated}",
                          "The gate must short-circuit inside score_bias for every caller."],
                bar_refs=[_hhmm(b.ist_dt)],
            )]
    return []


def _strangle_missing_hedge(cfg: StrangleConfig, trace: list[BarStatus]) -> list[Finding]:
    """With hedging on, an open short side should carry its protective long."""
    if not cfg.hedge_enabled:
        return []
    for b in trace:
        hedged = {lg.opt_type for lg in b.legs if lg.is_hedge}
        naked = sorted({lg.opt_type for lg in b.legs
                        if not lg.is_hedge and not lg.is_momentum} - hedged)
        if naked:
            return [Finding(
                id="F-NO-HEDGE", severity="info",
                title=f"Short {'/'.join(naked)} running unhedged with hedge_enabled = true",
                evidence=[f"first seen {_hhmm(b.ist_dt)}",
                          "The hedge strike scan may have found nothing in the premium band."],
                bar_refs=[_hhmm(b.ist_dt)],
            )]
    return []


# --------------------------------------------------------------------------- #
# Intraday directional
# --------------------------------------------------------------------------- #


def check_intraday(
    cfg: IntradayDirectionalConfig,
    res: DayResult,
    trace: list[IntradayBarStatus],
    decisions: list[dict[str, Any]],
) -> list[Finding]:
    """Run every intraday detector and return the findings, most severe first."""
    out: list[Finding] = []
    out += _check_pnl_reconciles(res)
    out += _check_flat_on_a_move(res, "Intraday")
    out += _intraday_halt_breach(cfg, res, trace)
    out += _intraday_never_true_conditions(trace)
    out += _intraday_roll_budget(cfg, trace)
    out += _check_stale_ltp([
        (b.ist_dt, f"{b.side} {b.strike:.0f}", b.ltp)
        for b in trace if b.ltp is not None and b.side and b.strike is not None
    ])
    return rank(out)


def _intraday_halt_breach(
    cfg: IntradayDirectionalConfig, res: DayResult, trace: list[IntradayBarStatus],
) -> list[Finding]:
    """No new risk after the day-loss cap fires."""
    if not res.done_reason.startswith("day_loss"):
        return []
    halt = next((b.ist_dt for b in trace if b.done_reason), None)
    if halt is None:
        return []
    late = [t for t in res.trades if _opens_risk(t) and t.bar_time > halt]
    if not late:
        return []
    return [Finding(
        id="F-HALT-BREACH", severity="high",
        title=f"{len(late)} new position(s) opened after the day-loss halt",
        evidence=[f"halt at {_hhmm(halt)} (cap {cfg.day_loss_limit:,.0f})"] +
                 [f"{_hhmm(t.bar_time)} SELL {t.opt_type} {t.strike:.0f}" for t in late[:5]],
        bar_refs=[_hhmm(t.bar_time) for t in late[:5]],
    )]


def _intraday_never_true_conditions(trace: list[IntradayBarStatus]) -> list[Finding]:
    """An entry condition that was never satisfied on either side, all session.

    This is the direct answer to "why did nothing trade today" — and if the same
    condition is never true across many days, it is a broken input, not a quiet market.
    """
    evaluated = [b for b in trace if b.entry_conditions]
    if not evaluated:
        return []
    keys: set[str] = set()
    for b in evaluated:
        for conds in b.entry_conditions.values():
            keys |= set(conds)
    never = sorted(
        k for k in keys
        if not any(conds.get(k) for b in evaluated for conds in b.entry_conditions.values())
    )
    if not never:
        return []
    return [Finding(
        id="F-COND-NEVER", severity="medium" if len(never) == len(keys) else "info",
        title=f"Entry condition(s) never satisfied on either side: {', '.join(never)}",
        evidence=[f"evaluated on {len(evaluated)} bars",
                  "If this repeats across days the input is probably unavailable, "
                  "not merely false."],
    )]


def _intraday_roll_budget(
    cfg: IntradayDirectionalConfig, trace: list[IntradayBarStatus],
) -> list[Finding]:
    """Rollups spent, versus the per-day budget."""
    used = max((b.rolls_today for b in trace), default=0)
    max_rolls = getattr(cfg, "max_rolls_per_day", None)
    if not used or max_rolls is None or used < max_rolls:
        return []
    return [Finding(
        id="F-ROLL-BUDGET", severity="info",
        title=f"Rollup budget exhausted ({used}/{max_rolls})",
        evidence=["Later premium decay could not be rolled; the leg ran to its exit rules."],
    )]
