"""Range / breakout / volume detectors: level breaks, strangle range, volume spike, gap."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pdp.events.detectors.base import PrevStore, RollingZ
from pdp.events.detectors.levels import collect_levels
from pdp.events.models import Event, EventType, Severity

if TYPE_CHECKING:
    from pdp.events.detectors.base import BarContext

# Level names treated as resistance (break = cross above) vs support (break = cross below).
_RESISTANCE = {"PDH", "PWH", "PMH", "R1", "R2", "R3", "CAM_R3", "CAM_R4"}
_SUPPORT = {"PDL", "PWL", "PML", "S1", "S2", "S3", "CAM_S3", "CAM_S4"}


class RangeVolumeDetectors:
    def __init__(self) -> None:
        self._p = PrevStore()
        self._vol = RollingZ(maxlen=40)
        self._last_close: dict[str, float] = {}
        self._last_day: dict[str, object] = {}

    def evaluate(self, ctx: BarContext) -> list[Event]:
        out: list[Event] = []
        sid, tf = ctx.security_id, ctx.timeframe
        u = ctx.underlying or sid
        close = ctx.close

        def ev(et: EventType, sev: Severity, title: str, msg: str, dedup: str, **payload: object) -> None:
            out.append(Event(
                event_type=et, severity=sev, security_id=sid, underlying=ctx.underlying,
                timeframe=tf, title=title, message=msg, payload=dict(payload), dedup_key=dedup,
            ))

        # Level breaks (resistance up / support down). Match the full level name —
        # names like R1/CAM_R4 carry a trailing digit that is part of the label, so
        # stripping digits here would miss them.
        for name, price in collect_levels(ctx):
            if name in _RESISTANCE:
                c = self._p.crossed(f"{sid}:{tf}:brk:{name}:{price:.0f}", close, price)
                if c > 0:
                    ev(EventType.LEVEL_BREAK, Severity.WARNING, f"broke {name}",
                       f"{u} {tf}: broke above {name} ({price:.0f})",
                       f"{sid}:{tf}:brk:{name}:up", level=name, level_price=round(price, 2))
            elif name in _SUPPORT:
                c = self._p.crossed(f"{sid}:{tf}:brk:{name}:{price:.0f}", close, price)
                if c < 0:
                    ev(EventType.LEVEL_BREAK, Severity.WARNING, f"broke {name}",
                       f"{u} {tf}: broke below {name} ({price:.0f})",
                       f"{sid}:{tf}:brk:{name}:dn", level=name, level_price=round(price, 2))

        # Custom range break (strangle band) — keyed by underlying prefix
        for rk, (lo, hi) in ctx.cfg.position_ranges.items():
            if not rk.upper().startswith((ctx.underlying or "").upper()):
                continue
            outside = close > hi or close < lo
            key = f"{sid}:{tf}:range:{rk}"
            was = bool(self._p.get(key))
            self._p.set(key, outside)
            if outside and not was:
                side = "above" if close > hi else "below"
                ev(EventType.CUSTOM_RANGE_BREAK, Severity.CRITICAL, f"range break {side}",
                   f"{u} {tf}: broke {side} {rk} range [{lo:g}, {hi:g}] at {close:.0f}",
                   f"{sid}:{tf}:range:{rk}:{side}", range_key=rk, low=lo, high=hi,
                   close=round(close, 2))

        # Volume spike (z-score over rolling window)
        if ctx.volume > 0:
            z = self._vol.push(f"{sid}:{tf}:vol", ctx.volume)
            if z is not None and z >= ctx.cfg.volume_spike_z:
                ev(EventType.VOLUME_SPIKE, Severity.WARNING, "volume spike",
                   f"{u} {tf}: volume spike z={z:.1f}",
                   f"{sid}:{tf}:volspike", z=round(z, 2), volume=ctx.volume)

        # Volume-profile rejection at VAH/VAL
        if ctx.snapshot is not None and ctx.snapshot.volume_profile is not None:
            vp = ctx.snapshot.volume_profile
            if ctx.high >= vp.vah and close < vp.vah:
                ev(EventType.VOLUME_SR, Severity.INFO, "VAH rejection",
                   f"{u} {tf}: rejected at value-area high {vp.vah:.0f}",
                   f"{sid}:{tf}:vahrej", level="VAH", price=round(vp.vah, 2))
            if ctx.low <= vp.val and close > vp.val:
                ev(EventType.VOLUME_SR, Severity.INFO, "VAL bounce",
                   f"{u} {tf}: bounced at value-area low {vp.val:.0f}",
                   f"{sid}:{tf}:valrej", level="VAL", price=round(vp.val, 2))

        # Gap up/down at session open
        bkey = f"{sid}:{tf}"
        day = ctx.bar_time.date()
        prev_close = self._last_close.get(bkey)
        prev_day = self._last_day.get(bkey)
        if prev_day is not None and day != prev_day and prev_close:
            gap_pct = (ctx.open - prev_close) / prev_close * 100.0
            if abs(gap_pct) >= ctx.cfg.gap_pct:
                d = "up" if gap_pct > 0 else "down"
                sev = Severity.WARNING if abs(gap_pct) < 2 * ctx.cfg.gap_pct else Severity.CRITICAL
                ev(EventType.GAP_OPEN, sev, f"gap {d} {gap_pct:+.1f}%",
                   f"{u} {tf}: gapped {d} {gap_pct:+.2f}% "
                   f"(open {ctx.open:.0f} vs prev close {prev_close:.0f})",
                   f"{sid}:{tf}:gap:{day}", gap_pct=round(gap_pct, 2), direction=d,
                   open=round(ctx.open, 2), prev_close=round(prev_close, 2))
        self._last_close[bkey] = close
        self._last_day[bkey] = day

        return out
