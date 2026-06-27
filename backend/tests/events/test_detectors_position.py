"""Position detector tests: OTM distance, trailing exit, MTM swing, momentum reversal."""
from __future__ import annotations

from types import SimpleNamespace

from pdp.events.detectors.position import PositionDetectors
from pdp.events.models import EventType, MonitoredPosition

from .conftest import ema, make_ctx, make_snapshot


def _pos(**kw) -> MonitoredPosition:
    base = dict(
        security_id="45678", underlying="NIFTY", exchange_segment="NSE_FNO",
        net_qty=-75, avg_price=120.0, side="SHORT", strike=24000.0,
        option_type="CE", expiry="2026-06-26", trading_symbol="NIFTY24000CE",
    )
    base.update(kw)
    return MonitoredPosition(**base)


class TestPositionTick:
    def test_otm_distance(self, cfg):
        det = PositionDetectors()
        pos = _pos()  # short 24000 CE; OTM while spot < 24000
        ltps = {"45678": 110.0}
        spots = {"NIFTY": 23950.0}  # within 100 pts of 24000
        evs = det.evaluate_tick([pos], ltps.get, spots.get, cfg)
        assert any(e.event_type == EventType.OTM_DISTANCE for e in evs)

    def test_mtm_swing_then_trail(self, cfg):
        det = PositionDetectors()
        pos = _pos(net_qty=75, avg_price=100.0, option_type="CE")  # long CE
        # baseline (first tick sets last_swing, no event)
        det.evaluate_tick([pos], {"45678": 100.0}.get, {"NIFTY": 24000.0}.get, cfg)
        # premium rises → MTM peak +7500
        det.evaluate_tick([pos], {"45678": 200.0}.get, {"NIFTY": 24000.0}.get, cfg)
        assert pos.mtm_peak >= 7000
        # retrace ≥30% → SAFE_TO_EXIT_TRAIL
        evs = det.evaluate_tick([pos], {"45678": 130.0}.get, {"NIFTY": 24000.0}.get, cfg)
        assert any(e.event_type == EventType.SAFE_TO_EXIT_TRAIL for e in evs)

    def test_no_ltp_no_event(self, cfg):
        det = PositionDetectors()
        assert det.evaluate_tick([_pos()], lambda s: None, lambda u: None, cfg) == []


class TestPositionBar:
    def test_momentum_reversal_against_long_ce(self, cfg):
        det = PositionDetectors()
        pos = _pos(net_qty=75, option_type="CE")  # bullish bias
        # PSAR down + price below EMA50 → adverse
        snap = make_snapshot(psar=SimpleNamespace(direction=-1, sar=24100), ema=ema({50: 24050}))
        ctx = make_ctx(cfg, c=24000, snapshot=snap)
        evs = det.evaluate_bar(ctx, [pos])
        assert any(e.event_type == EventType.SAFE_TO_EXIT_MOMENTUM for e in evs)
