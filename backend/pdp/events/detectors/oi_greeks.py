"""Option-chain detectors: OI walls, buildup, PCR, GEX, max-pain, IV, delta, breakeven."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pdp.events.detectors.base import PrevStore, RollingZ
from pdp.events.models import Event, EventType, Severity
from pdp.options import analytics

if TYPE_CHECKING:
    from pdp.events.config import EventConfig
    from pdp.events.models import MonitoredPosition


def _atm(strikes: list[dict[str, Any]], spot: float) -> float | None:
    if not strikes or spot <= 0:
        return None
    return min((float(s["strike"]) for s in strikes), key=lambda k: abs(k - spot))


def _leg(s: dict[str, Any], which: str) -> dict[str, Any]:
    v = s.get(which)
    return cast("dict[str, Any]", v) if isinstance(v, dict) else {}


def _f(d: dict[str, Any], key: str) -> float:
    v = d.get(key)
    return float(v) if v else 0.0


class OIGreeksDetectors:
    def __init__(self) -> None:
        self._p = PrevStore()
        self._oi_vol = RollingZ(maxlen=30)
        self._iv = RollingZ(maxlen=30)
        self._oi_base: dict[tuple[str, float, str], float] = {}
        self._day: dict[str, object] = {}
        self._walls: dict[str, list[tuple[str, float]]] = {}

    def walls(self, underlying: str) -> list[tuple[str, float]]:
        return self._walls.get(underlying.upper(), [])

    def evaluate(
        self,
        doc: dict[str, Any],
        positions: list[MonitoredPosition],
        cfg: EventConfig,
    ) -> list[Event]:
        out: list[Event] = []
        u = str(doc.get("underlying", "")).upper()
        strikes: list[dict[str, Any]] = doc.get("strikes") or []
        spot = float(doc.get("spot_price") or 0.0)
        if not strikes or spot <= 0:
            return out
        held = {p.strike for p in positions if p.underlying.upper() == u and p.strike}

        def ev(et: EventType, sev: Severity, title: str, msg: str, dedup: str, **payload: object) -> None:
            out.append(Event(
                event_type=et, severity=sev, security_id=u, underlying=u, title=title,
                message=msg, payload=dict(payload), dedup_key=dedup,
            ))

        # daily reset of OI baselines
        from datetime import date
        ts: Any = doc.get("snapshot_ts")
        today = ts.date() if hasattr(ts, "date") else date.today()
        if self._day.get(u) != today:
            self._day[u] = today
            for k in [k for k in self._oi_base if k[0] == u]:
                del self._oi_base[k]

        # OI walls (max CE OI = resistance, max PE OI = support)
        ce_wall = max(strikes, key=lambda s: _f(_leg(s, "ce"), "oi"), default=None)
        pe_wall = max(strikes, key=lambda s: _f(_leg(s, "pe"), "oi"), default=None)
        walls: list[tuple[str, float]] = []
        if ce_wall:
            walls.append(("OI_R", float(ce_wall["strike"])))
        if pe_wall:
            walls.append(("OI_S", float(pe_wall["strike"])))
        self._walls[u] = walls
        for label, price in walls:
            if abs(spot - price) <= cfg.gex_wall_pts:
                kind = "resistance" if label == "OI_R" else "support"
                ev(EventType.OI_WALL, Severity.WARNING, f"OI {kind} {price:g}",
                   f"{u}: spot {spot:.0f} at strong OI {kind} {price:g}",
                   f"{u}:oiwall:{label}", strike=price, kind=kind)

        # PCR band cross
        pcr = doc.get("pcr")
        if pcr is not None:
            for band in cfg.pcr_bands:
                c = self._p.crossed(f"{u}:pcr:{band}", float(pcr), band)
                if c != 0:
                    d = "above" if c > 0 else "below"
                    ev(EventType.PCR_SHIFT, Severity.WARNING, f"PCR {d} {band:g}",
                       f"{u}: PCR {pcr:.2f} crossed {d} {band:g}", f"{u}:pcr:{band}:{d}",
                       pcr=round(float(pcr), 3), band=band)

        # GEX wall proximity
        try:
            gex = analytics.compute_gex(strikes, lot_size=1, spot=spot)
            per: list[dict[str, Any]] = gex.get("per_strike") or []
            if per:
                top = max(per, key=lambda x: abs(_f(x, "gex")))
                gk = float(top["strike"])
                if abs(spot - gk) <= cfg.gex_wall_pts:
                    ev(EventType.GEX_WALL, Severity.WARNING, f"GEX wall {gk:g}",
                       f"{u}: spot {spot:.0f} near peak-gamma {gk:g}", f"{u}:gexwall",
                       strike=gk, net_gex=round(float(gex.get("net_gex", 0.0)), 2))
        except Exception:  # noqa: S110
            pass

        # Max-pain shift / pin
        mp = doc.get("max_pain")
        if mp is not None and self._p.changed(f"{u}:maxpain", mp):
            ev(EventType.MAX_PAIN_PIN, Severity.INFO, f"max-pain {mp:g}",
               f"{u}: max-pain shifted to {mp:g} (spot {spot:.0f})", f"{u}:maxpain",
               max_pain=mp, spot=round(spot, 2))

        # OI buildup + OI/volume spike at ATM±band / held strikes
        atm = _atm(strikes, spot)
        for s in strikes:
            strike = float(s["strike"])
            watch = strike in held or (atm is not None and abs(strike - atm) <= 3 * 50)
            if not watch:
                continue
            for side in ("ce", "pe"):
                leg = _leg(s, side)
                oi = _f(leg, "oi")
                vol = _f(leg, "volume")
                k = (u, strike, side.upper())
                base = self._oi_base.get(k)
                if base is None and oi > 0:
                    self._oi_base[k] = oi
                elif base and base > 0:
                    pct = (oi - base) / base * 100.0
                    if pct >= cfg.oi_buildup_pct:
                        ev(EventType.OI_BUILDUP, Severity.INFO, f"OI+ {strike:g}{side.upper()}",
                           f"{u}: OI built {pct:.0f}% at {strike:g} {side.upper()}",
                           f"{u}:oibuild:{strike}:{side}", strike=strike, side=side.upper(),
                           pct=round(pct, 1))
                if vol > 0:
                    z = self._oi_vol.push(f"{u}:{strike}:{side}", float(vol))
                    if z is not None and z >= cfg.oi_volume_spike_z:
                        ev(EventType.OI_VOLUME_SPIKE, Severity.WARNING,
                           f"vol spike {strike:g}{side.upper()}",
                           f"{u}: volume spike z={z:.1f} at {strike:g} {side.upper()}",
                           f"{u}:oivol:{strike}:{side}", strike=strike, side=side.upper(), z=round(z, 2))

        # ATM IV spike/crush
        if atm is not None:
            atm_row = next((s for s in strikes if float(s["strike"]) == atm), None)
            if atm_row:
                ivs = [v for v in (_f(_leg(atm_row, "ce"), "iv"), _f(_leg(atm_row, "pe"), "iv")) if v]
                if ivs:
                    iv = sum(ivs) / len(ivs)
                    z = self._iv.push(f"{u}:atmiv", float(iv))
                    if z is not None and abs(z) >= 3.0:
                        kind = "spike" if z > 0 else "crush"
                        ev(EventType.IV_SHIFT, Severity.WARNING, f"IV {kind}",
                           f"{u}: ATM IV {kind} (z={z:.1f}, iv={iv:.1f})", f"{u}:ivshift",
                           iv=round(float(iv), 2), z=round(z, 2))

        # Portfolio delta-neutral drift + breakeven (multi-leg)
        out.extend(self._greeks_position(u, spot, positions, cfg))
        return out

    def _greeks_position(
        self, u: str, spot: float, positions: list[MonitoredPosition], cfg: EventConfig,
    ) -> list[Event]:
        out: list[Event] = []
        legs = [p for p in positions if p.underlying.upper() == u and p.is_option]
        if not legs:
            return out

        # Aggregate net delta (delta * net_qty)
        deltas = [(p.delta * p.net_qty) for p in legs if p.delta is not None]
        total_qty = sum(abs(p.net_qty) for p in legs) or 1
        if deltas:
            net = sum(deltas)
            if abs(net) > cfg.delta_neutral_band * total_qty:
                d = "long" if net > 0 else "short"
                out.append(Event(
                    event_type=EventType.DELTA_NEUTRAL_DRIFT, severity=Severity.WARNING,
                    security_id=u, underlying=u, title=f"delta {d} {net:+.0f}",
                    message=f"{u}: net portfolio delta {net:+.0f} ({d}) — drifted from neutral",
                    payload={"net_delta": round(net, 1)}, dedup_key=f"{u}:deltadrift",
                ))

        # Strangle/straddle breakeven (two short legs CE & PE)
        shorts = [p for p in legs if p.net_qty < 0]
        ce = next((p for p in shorts if p.option_type == "CE" and p.strike), None)
        pe = next((p for p in shorts if p.option_type == "PE" and p.strike), None)
        if ce and pe and ce.strike and pe.strike:
            prem = ce.avg_price + pe.avg_price
            be_up, be_dn = ce.strike + prem, pe.strike - prem
            if spot > be_up or spot < be_dn:
                side = "above" if spot > be_up else "below"
                out.append(Event(
                    event_type=EventType.BREAKEVEN_BREACH, severity=Severity.CRITICAL,
                    security_id=u, underlying=u, title=f"breakeven {side}",
                    message=(f"{u}: spot {spot:.0f} breached {side} breakeven "
                             f"[{be_dn:.0f}, {be_up:.0f}]"),
                    payload={"spot": round(spot, 2), "be_up": round(be_up, 1), "be_dn": round(be_dn, 1)},
                    dedup_key=f"{u}:breakeven:{side}",
                ))
        return out
