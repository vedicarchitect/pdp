"""Snapshot bundle: latest *State for every configured indicator family."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdp.indicators.ema import EMAState
    from pdp.indicators.fvg import FVGState
    from pdp.indicators.market_profile import MarketProfileState
    from pdp.indicators.pivots import PivotState
    from pdp.indicators.psar import ParabolicSARState
    from pdp.indicators.rsi import RSIState
    from pdp.indicators.volume_profile import VolumeProfileState
    from pdp.indicators.vwap import VWAPState
    from pdp.indicators.vwma import VWMAState


@dataclass(slots=True)
class Snapshot:
    ema: EMAState | None = None
    rsi: RSIState | None = None
    psar: ParabolicSARState | None = None
    vwap: VWAPState | None = None
    vwma: VWMAState | None = None
    pivots: PivotState | None = None
    fvg: FVGState | None = None
    volume_profile: VolumeProfileState | None = None
    market_profile: MarketProfileState | None = None

    def to_dict(self) -> dict[str, Any]:
        """Lightweight serialisation for Redis publish (non-critical path)."""
        d: dict[str, Any] = {}
        if self.ema is not None:
            d["ema"] = {str(k): round(v, 4) for k, v in self.ema.values.items()}
        if self.rsi is not None:
            d["rsi"] = round(self.rsi.rsi, 4)
            if self.rsi.ma is not None:
                d["rsi_ma"] = round(self.rsi.ma, 4)
        if self.psar is not None:
            d["psar"] = {"sar": round(self.psar.sar, 4), "dir": self.psar.direction}
        if self.vwap is not None:
            d["vwap"] = round(self.vwap.vwap, 4)
        if self.vwma is not None:
            d["vwma"] = round(self.vwma.vwma, 4)
        if self.pivots is not None:
            pv = self.pivots
            d["pivots"] = {
                "pp": round(pv.pp, 2), "r1": round(pv.r1, 2), "s1": round(pv.s1, 2),
                "cam_r3": round(pv.cam_r3, 2), "cam_s3": round(pv.cam_s3, 2),
                "fib_r1": round(pv.fib_r1, 2), "fib_s1": round(pv.fib_s1, 2),
            }
        if self.fvg is not None:
            d["fvg"] = {"unfilled": self.fvg.unfilled_count, "total": self.fvg.total_gaps}
        if self.volume_profile is not None:
            vp = self.volume_profile
            d["volume_profile"] = {"poc": round(vp.poc, 2), "vah": round(vp.vah, 2), "val": round(vp.val, 2)}
        if self.market_profile is not None:
            d["market_profile"] = {"poc": round(self.market_profile.poc, 2)}
        return d
