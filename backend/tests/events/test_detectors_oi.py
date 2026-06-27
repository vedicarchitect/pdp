"""OI/Greeks detector tests: OI wall, PCR shift, max-pain, delta drift, breakeven."""
from __future__ import annotations

from datetime import UTC, datetime

from pdp.events.detectors.oi_greeks import OIGreeksDetectors
from pdp.events.models import EventType, MonitoredPosition


def _chain(spot: float, pcr: float | None = 1.0, max_pain: int | None = 24000) -> dict:
    return {
        "underlying": "NIFTY",
        "snapshot_ts": datetime(2026, 6, 17, 5, 0, tzinfo=UTC),
        "spot_price": spot,
        "pcr": pcr,
        "max_pain": max_pain,
        "strikes": [
            {"strike": 23900, "ce": {"oi": 1000, "volume": 10, "gamma": 0.001, "iv": 12},
             "pe": {"oi": 5000, "volume": 10, "gamma": 0.001, "iv": 12}},
            {"strike": 24000, "ce": {"oi": 9000, "volume": 10, "gamma": 0.002, "iv": 13},
             "pe": {"oi": 1000, "volume": 10, "gamma": 0.002, "iv": 13}},
            {"strike": 24100, "ce": {"oi": 2000, "volume": 10, "gamma": 0.001, "iv": 12},
             "pe": {"oi": 800, "volume": 10, "gamma": 0.001, "iv": 12}},
        ],
    }


class TestOI:
    def test_oi_wall_resistance(self, cfg):
        det = OIGreeksDetectors()
        evs = det.evaluate(_chain(spot=23990), [], cfg)  # near 24000 CE wall
        walls = [e for e in evs if e.event_type == EventType.OI_WALL]
        assert walls and any(e.payload["kind"] == "resistance" for e in walls)
        # walls cached for confluence injection
        assert ("OI_R", 24000.0) in det.walls("NIFTY")

    def test_pcr_band_cross(self, cfg):
        det = OIGreeksDetectors()
        det.evaluate(_chain(spot=23800, pcr=1.2), [], cfg)
        evs = det.evaluate(_chain(spot=23800, pcr=1.35), [], cfg)
        assert any(e.event_type == EventType.PCR_SHIFT for e in evs)

    def test_max_pain_shift(self, cfg):
        det = OIGreeksDetectors()
        det.evaluate(_chain(spot=23800, max_pain=24000), [], cfg)
        evs = det.evaluate(_chain(spot=23800, max_pain=24100), [], cfg)
        assert any(e.event_type == EventType.MAX_PAIN_PIN for e in evs)


class TestGreeks:
    def test_delta_neutral_drift(self, cfg):
        det = OIGreeksDetectors()
        legs = [
            MonitoredPosition(security_id="1", underlying="NIFTY", exchange_segment="NSE_FNO",
                              net_qty=-75, avg_price=100, side="SHORT", strike=24000,
                              option_type="CE", delta=0.6),
            MonitoredPosition(security_id="2", underlying="NIFTY", exchange_segment="NSE_FNO",
                              net_qty=-75, avg_price=90, side="SHORT", strike=23800,
                              option_type="PE", delta=0.1),
        ]
        evs = det.evaluate(_chain(spot=24050), legs, cfg)
        assert any(e.event_type == EventType.DELTA_NEUTRAL_DRIFT for e in evs)

    def test_breakeven_breach(self, cfg):
        det = OIGreeksDetectors()
        legs = [
            MonitoredPosition(security_id="1", underlying="NIFTY", exchange_segment="NSE_FNO",
                              net_qty=-75, avg_price=100, side="SHORT", strike=24000,
                              option_type="CE", delta=0.5),
            MonitoredPosition(security_id="2", underlying="NIFTY", exchange_segment="NSE_FNO",
                              net_qty=-75, avg_price=100, side="SHORT", strike=23000,
                              option_type="PE", delta=-0.5),
        ]
        # premium 200 → be_up = 24200; spot 24300 breaches
        evs = det.evaluate(_chain(spot=24300), legs, cfg)
        assert any(e.event_type == EventType.BREAKEVEN_BREACH for e in evs)
