"""Trend / momentum detectors (per timeframe): EMA cross, SuperTrend, PSAR, MACD, etc."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pdp.events.detectors.base import PrevStore
from pdp.events.models import Event, EventType, Severity

if TYPE_CHECKING:
    from pdp.events.detectors.base import BarContext

_DIR = {1: "up", -1: "down", 0: "flat"}


class TrendDetectors:
    def __init__(self) -> None:
        self._p = PrevStore()

    def evaluate(self, ctx: BarContext) -> list[Event]:
        out: list[Event] = []
        sid, tf = ctx.security_id, ctx.timeframe
        u = ctx.underlying or sid
        snap = ctx.snapshot

        def ev(et: EventType, sev: Severity, title: str, msg: str, **payload: object) -> None:
            out.append(Event(
                event_type=et, severity=sev, security_id=sid, underlying=ctx.underlying,
                timeframe=tf, title=title, message=msg, payload=dict(payload),
                dedup_key=f"{sid}:{tf}:{et.value}:{title}",
            ))

        # EMA crossovers (configured pairs)
        if snap is not None and snap.ema is not None:
            vals = snap.ema.values
            for fast, slow in ctx.cfg.ema_pairs:
                fv, sv = vals.get(fast), vals.get(slow)
                if fv is None or sv is None:
                    continue
                c = self._p.crossed(f"{sid}:{tf}:emax:{fast}/{slow}", fv, sv)
                if c != 0:
                    d = "above" if c > 0 else "below"
                    ev(EventType.EMA_CROSS, Severity.WARNING,
                       f"{fast}>{slow} EMA {d}", f"{u} {tf}: {fast}-EMA crossed {d} {slow}-EMA",
                       fast=fast, slow=slow, fast_val=round(fv, 2), slow_val=round(sv, 2))
            # price vs EMA
            for p in ctx.cfg.price_ema_periods:
                pv = vals.get(p)
                if pv is None:
                    continue
                c = self._p.crossed(f"{sid}:{tf}:pxema:{p}", ctx.close, pv)
                if c != 0:
                    d = "above" if c > 0 else "below"
                    ev(EventType.PRICE_EMA_CROSS, Severity.WARNING,
                       f"price {d} {p}EMA", f"{u} {tf}: price crossed {d} the {p}-EMA ({pv:.1f})",
                       period=p, ema=round(pv, 2), close=round(ctx.close, 2))

        # SuperTrend flip
        if ctx.supertrend is not None:
            dirn = int(ctx.supertrend.direction)
            if self._p.changed(f"{sid}:{tf}:st", dirn):
                sev = Severity.CRITICAL if tf in ("1H", "1D") else Severity.WARNING
                ev(EventType.SUPERTREND_FLIP, sev, f"SuperTrend {_DIR[dirn]}",
                   f"{u} {tf}: SuperTrend(10,2) flipped {_DIR[dirn]}", direction=dirn)

        if snap is None:
            return out

        # Parabolic SAR flip
        if snap.psar is not None:
            d = int(snap.psar.direction)
            if self._p.changed(f"{sid}:{tf}:psar", d):
                ev(EventType.PSAR_FLIP, Severity.WARNING, f"PSAR {_DIR[d]}",
                   f"{u} {tf}: Parabolic SAR flipped {_DIR[d]}", direction=d,
                   sar=round(snap.psar.sar, 2))

        # MACD line vs signal cross
        if snap.macd is not None:
            c = self._p.crossed(f"{sid}:{tf}:macd", snap.macd.macd, snap.macd.signal)
            if c != 0:
                d = "bullish" if c > 0 else "bearish"
                ev(EventType.MACD_CROSS, Severity.WARNING, f"MACD {d}",
                   f"{u} {tf}: MACD crossed {d} its signal",
                   macd=round(snap.macd.macd, 3), signal=round(snap.macd.signal, 3))

        # Elder impulse regime change
        if snap.elder_impulse is not None:
            if self._p.changed(f"{sid}:{tf}:elder", snap.elder_impulse.regime):
                ev(EventType.ELDER_IMPULSE_CHANGE, Severity.INFO,
                   f"Elder {snap.elder_impulse.regime}",
                   f"{u} {tf}: Elder impulse → {snap.elder_impulse.regime}",
                   regime=snap.elder_impulse.regime)

        # Elliott wave label change
        if snap.elliott is not None and snap.elliott.wave_label is not None:
            if self._p.changed(f"{sid}:{tf}:elliott", snap.elliott.wave_label):
                ev(EventType.ELLIOTT_WAVE, Severity.INFO,
                   f"Elliott {snap.elliott.wave_label}",
                   f"{u} {tf}: Elliott wave → {snap.elliott.wave_label} "
                   f"(conf {snap.elliott.confidence:.0%})",
                   wave_label=snap.elliott.wave_label, confidence=round(snap.elliott.confidence, 3))

        # RSI extreme zone entry
        if snap.rsi is not None:
            zone = "OB" if snap.rsi.rsi >= 70 else ("OS" if snap.rsi.rsi <= 30 else "")
            if zone and self._p.changed(f"{sid}:{tf}:rsizone", zone):
                lbl = "overbought" if zone == "OB" else "oversold"
                ev(EventType.RSI_EXTREME, Severity.WARNING, f"RSI {lbl}",
                   f"{u} {tf}: RSI {snap.rsi.rsi:.0f} ({lbl})", rsi=round(snap.rsi.rsi, 1))

        # ML signal flip
        if ctx.ml_signal is not None:
            label = (getattr(ctx.ml_signal, "argmax", None)
                     or getattr(ctx.ml_signal, "direction", None)
                     or getattr(ctx.ml_signal, "label", None))
            if label is not None and self._p.changed(f"{sid}:{tf}:ml", str(label)):
                ev(EventType.ML_SIGNAL_FLIP, Severity.WARNING, f"ML {label}",
                   f"{u} {tf}: ML directional signal → {label}", label=str(label))

        return out
