"""Price-level, proximity, and confluence detectors."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pdp.events.detectors.base import PrevStore
from pdp.events.models import Event, EventType, Severity

if TYPE_CHECKING:
    from pdp.events.detectors.base import BarContext


def collect_levels(ctx: BarContext) -> list[tuple[str, float]]:
    """Gather named price levels from the warehouse/snapshot + injected OI walls.

    Camarilla + period levels (CAM_*/PDH/PDL/PWH/PWL/PMH/PML) come from the persisted
    ``index_levels`` warehouse when injected (``ctx.warehouse_levels``) so level events
    agree with the Execution-tab matrix; otherwise they fall back to the live snapshot.
    """
    out: list[tuple[str, float]] = []
    # Authoritative warehouse levels (same source as the matrix), when injected.
    wh = list(ctx.warehouse_levels or ())
    wh_labels = {label for label, _ in wh}
    out.extend(wh)

    snap = ctx.snapshot
    if snap is not None:
        pl = snap.period_levels
        if pl is not None:
            for name, v in (
                ("PDH", pl.pdh), ("PDL", pl.pdl), ("PWH", pl.pwh),
                ("PWL", pl.pwl), ("PMH", pl.pmh), ("PML", pl.pml),
            ):
                if v is not None and name not in wh_labels:
                    out.append((name, float(v)))
        pv = snap.pivots
        if pv is not None:
            for name, v in (
                ("PP", pv.pp), ("R1", pv.r1), ("R2", pv.r2), ("R3", pv.r3),
                ("S1", pv.s1), ("S2", pv.s2), ("S3", pv.s3),
                ("CAM_R3", pv.cam_r3), ("CAM_R4", pv.cam_r4),
                ("CAM_S3", pv.cam_s3), ("CAM_S4", pv.cam_s4),
            ):
                if name not in wh_labels:
                    out.append((name, float(v)))
        if snap.vwap is not None:
            out.append(("VWAP", float(snap.vwap.vwap)))
        if snap.fib_levels is not None and snap.fib_levels.nearest_level:
            out.append(("FIB", float(snap.fib_levels.nearest_level)))
        if snap.ema is not None:
            for p in ctx.cfg.price_ema_periods:
                v = snap.ema.values.get(p)
                if v is not None:
                    out.append((f"EMA{p}", float(v)))
        if snap.fvg is not None:
            for gap in getattr(snap.fvg, "unfilled_gaps", []) or []:
                lo = getattr(gap, "gap_low", None)
                hi = getattr(gap, "gap_high", None)
                if lo is not None and hi is not None:
                    out.append(("FVG", (float(lo) + float(hi)) / 2.0))
    for label, price in ctx.oi_levels or ():
        out.append((label, float(price)))
    return out


class LevelDetectors:
    def __init__(self) -> None:
        self._p = PrevStore()

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

        # Custom watch-level crosses (configured per underlying)
        levels = ctx.cfg.watch_levels.get((ctx.underlying or "").upper(), [])
        for lv in levels:
            c = self._p.crossed(f"{sid}:{tf}:wlx:{lv}", close, lv)
            if c != 0:
                d = "above" if c > 0 else "below"
                ev(EventType.PRICE_LEVEL_CROSS, Severity.WARNING, f"crossed {lv:g} {d}",
                   f"{u} {tf}: price crossed {d} {lv:g}", f"{sid}:{tf}:wlx:{lv}:{d}",
                   level=lv, close=round(close, 2))

        named = collect_levels(ctx)

        _CAM_LEVELS = frozenset({"CAM_R3", "CAM_R4", "CAM_S3", "CAM_S4"})

        # Proximity: price within band of a notable level
        band = ctx.cfg.proximity_band_pts
        for name, price in named:
            dist = abs(close - price)
            near = dist <= band
            key = f"{sid}:{tf}:prox:{name}:{price:.0f}"
            was_near = bool(self._p.get(key))
            self._p.set(key, near)
            if near and not was_near:
                if name in _CAM_LEVELS:
                    ev(EventType.CAMARILLA_TOUCH, Severity.WARNING, f"Camarilla {name} touch",
                       f"{u} {tf}: price {close:.0f} touching {name} ({price:.0f})",
                       f"{sid}:{tf}:cam:{name}", level=name, level_price=round(price, 2),
                       distance=round(dist, 1))
                else:
                    ev(EventType.LEVEL_PROXIMITY, Severity.INFO, f"near {name}",
                       f"{u} {tf}: price {close:.0f} within {dist:.0f} pts of {name} ({price:.0f})",
                       f"{sid}:{tf}:prox:{name}", level=name, level_price=round(price, 2),
                       distance=round(dist, 1))

        # Confluence: ≥ N distinct sources clustered within band of price
        cband = ctx.cfg.confluence_band_pts
        cluster = [(n, p) for n, p in named if abs(close - p) <= cband]
        # distinct source families (strip trailing digits like EMA50 → EMA)
        fams = {n.rstrip("0123456789") for n, _ in cluster}
        if len(fams) >= ctx.cfg.confluence_min:
            sev = Severity.CRITICAL if len(fams) >= ctx.cfg.confluence_min + 1 else Severity.WARNING
            srcs = ", ".join(f"{n}@{p:.0f}" for n, p in cluster)
            ev(EventType.CONFLUENCE_ZONE, sev, f"confluence x{len(fams)}",
               f"{u} {tf}: price {close:.0f} at confluence of {len(fams)} sources — {srcs}",
               f"{sid}:{tf}:confluence", sources=[n for n, _ in cluster],
               levels=[round(p, 2) for _, p in cluster], count=len(fams))

        return out
