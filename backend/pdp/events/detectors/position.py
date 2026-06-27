"""Position-aware detectors: MTM swing, OTM distance, safe-to-exit, leg stop, junction."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pdp.events.detectors.base import PrevStore
from pdp.events.models import Event, EventType, Severity

if TYPE_CHECKING:
    from pdp.events.config import EventConfig
    from pdp.events.detectors.base import BarContext
    from pdp.events.models import MonitoredPosition


def _bias(pos: MonitoredPosition) -> int:
    """+1 bullish, -1 bearish, 0 non-directional, for an option leg."""
    if pos.option_type not in ("CE", "PE"):
        return 1 if pos.net_qty > 0 else (-1 if pos.net_qty < 0 else 0)
    long = pos.net_qty > 0
    if pos.option_type == "CE":
        return 1 if long else -1
    return -1 if long else 1


def mtm_of(pos: MonitoredPosition, ltp: float) -> float:
    return pos.net_qty * (ltp - pos.avg_price)


class PositionDetectors:
    def __init__(self) -> None:
        self._p = PrevStore()
        self._last_swing: dict[str, float] = {}

    # ── tick-driven ──────────────────────────────────────────────────────────
    def evaluate_tick(
        self,
        positions: list[MonitoredPosition],
        ltp_of: Callable[[str], float | None],
        spot_of: Callable[[str], float | None],
        cfg: EventConfig,
    ) -> list[Event]:
        out: list[Event] = []
        for pos in positions:
            ltp = ltp_of(pos.security_id)
            if ltp is None:
                continue
            mtm = mtm_of(pos, ltp)
            pos.last_mtm = mtm
            if mtm > pos.mtm_peak:
                pos.mtm_peak = mtm
            sym = pos.trading_symbol or pos.security_id

            # MTM swing since last emission
            last = self._last_swing.get(pos.key)
            if last is None or abs(mtm - last) >= cfg.mtm_swing_inr:
                self._last_swing[pos.key] = mtm
                if last is not None:
                    sev = Severity.WARNING if mtm < last else Severity.INFO
                    out.append(Event(
                        event_type=EventType.MTM_SWING, severity=sev, security_id=pos.security_id,
                        underlying=pos.underlying, title=f"MTM {mtm:+.0f}",
                        message=f"{sym}: MTM {mtm:+.0f} (Δ {mtm - last:+.0f})",
                        payload={"mtm": round(mtm, 0), "delta": round(mtm - last, 0),
                                 "ltp": ltp, "qty": pos.net_qty},
                        dedup_key=f"{pos.key}:mtm_swing",
                    ))

            # Trailing safe-to-exit
            if pos.mtm_peak > 0:
                giveback = pos.mtm_peak * (cfg.trail_giveback_pct / 100.0)
                if mtm <= pos.mtm_peak - giveback and pos.mtm_peak - mtm > 0:
                    out.append(Event(
                        event_type=EventType.SAFE_TO_EXIT_TRAIL, severity=Severity.WARNING,
                        security_id=pos.security_id, underlying=pos.underlying,
                        title="trail exit", message=(
                            f"{sym}: MTM gave back {cfg.trail_giveback_pct:.0f}% "
                            f"(peak {pos.mtm_peak:+.0f} → {mtm:+.0f}) — consider exit"),
                        payload={"peak": round(pos.mtm_peak, 0), "mtm": round(mtm, 0)},
                        dedup_key=f"{pos.key}:trail_exit",
                    ))

            # OTM distance (option legs only)
            if pos.is_option and pos.strike is not None:
                spot = spot_of(pos.underlying)
                if spot is not None:
                    is_otm = (pos.option_type == "CE" and pos.strike > spot) or (
                        pos.option_type == "PE" and pos.strike < spot)
                    dist = abs(spot - pos.strike)
                    if is_otm and dist <= cfg.otm_distance_pts:
                        out.append(Event(
                            event_type=EventType.OTM_DISTANCE, severity=Severity.WARNING,
                            security_id=pos.security_id, underlying=pos.underlying,
                            title=f"{dist:.0f}pts to {pos.strike:g}{pos.option_type}",
                            message=(f"{pos.underlying} spot {spot:.0f} within {dist:.0f} pts of your "
                                     f"{pos.strike:g} {pos.option_type}"),
                            payload={"spot": round(spot, 2), "strike": pos.strike,
                                     "distance": round(dist, 1)},
                            dedup_key=f"{pos.key}:otm_distance",
                        ))

            # Leg stop proximity (heuristic: adverse premium move ≥ 40%)
            if pos.is_option and pos.avg_price > 0:
                adverse = (ltp - pos.avg_price) / pos.avg_price if pos.net_qty < 0 else (
                    pos.avg_price - ltp) / pos.avg_price
                if adverse >= 0.40:
                    out.append(Event(
                        event_type=EventType.LEG_STOP_PROXIMITY, severity=Severity.WARNING,
                        security_id=pos.security_id, underlying=pos.underlying,
                        title="leg stop near", message=(
                            f"{sym}: premium moved {adverse:.0%} against you (avg {pos.avg_price:.1f} "
                            f"→ {ltp:.1f})"),
                        payload={"avg": pos.avg_price, "ltp": ltp, "adverse_pct": round(adverse * 100, 1)},
                        dedup_key=f"{pos.key}:leg_stop",
                    ))
        return out

    # ── bar-driven (momentum reversal / directional junction) ─────────────────
    def evaluate_bar(self, ctx: BarContext, positions: list[MonitoredPosition]) -> list[Event]:
        out: list[Event] = []
        snap = ctx.snapshot
        if snap is None or not positions:
            return out
        psar_dir = int(snap.psar.direction) if snap.psar is not None else None
        ema50 = snap.ema.values.get(50) if snap.ema is not None else None

        for pos in positions:
            bias = _bias(pos)
            if bias == 0:
                continue
            sym = pos.trading_symbol or pos.security_id
            # adverse momentum: PSAR + price/EMA50 both against the position bias
            psar_adverse = psar_dir is not None and psar_dir == -bias
            px_adverse = ema50 is not None and (
                (bias > 0 and ctx.close < ema50) or (bias < 0 and ctx.close > ema50))
            if psar_adverse and px_adverse:
                if not self._p.get(f"{pos.key}:{ctx.timeframe}:momadv"):
                    self._p.set(f"{pos.key}:{ctx.timeframe}:momadv", True)
                    out.append(Event(
                        event_type=EventType.SAFE_TO_EXIT_MOMENTUM, severity=Severity.WARNING,
                        security_id=pos.security_id, underlying=pos.underlying, timeframe=ctx.timeframe,
                        title="momentum reversal", message=(
                            f"{sym}: {ctx.timeframe} momentum turned against your "
                            f"{'bullish' if bias > 0 else 'bearish'} position (PSAR + EMA50)"),
                        payload={"bias": bias, "close": round(ctx.close, 2),
                                 "ema50": round(ema50, 2) if ema50 else None},
                        dedup_key=f"{pos.key}:{ctx.timeframe}:mom_exit",
                    ))
            else:
                self._p.set(f"{pos.key}:{ctx.timeframe}:momadv", False)

            # Directional junction: SuperTrend flips against a directional position
            if ctx.supertrend is not None:
                st = int(ctx.supertrend.direction)
                if st == -bias and self._p.changed(f"{pos.key}:{ctx.timeframe}:stbias", st):
                    out.append(Event(
                        event_type=EventType.DIRECTIONAL_JUNCTION, severity=Severity.WARNING,
                        security_id=pos.security_id, underlying=pos.underlying, timeframe=ctx.timeframe,
                        title="critical junction", message=(
                            f"{sym}: {ctx.timeframe} SuperTrend flipped against your position — "
                            f"critical junction"),
                        payload={"supertrend": st, "bias": bias},
                        dedup_key=f"{pos.key}:{ctx.timeframe}:junction",
                    ))
        return out
