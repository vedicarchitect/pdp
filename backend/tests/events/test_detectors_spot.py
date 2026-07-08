"""Spot/indicator detector tests: edge-triggering for trend + levels + range/volume."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from pdp.events.detectors.levels import LevelDetectors
from pdp.events.detectors.range_volume import RangeVolumeDetectors
from pdp.events.detectors.trend import TrendDetectors
from pdp.events.models import EventType

from .conftest import ema, make_ctx, make_snapshot


class TestTrend:
    def test_ema_cross_fires_once_per_edge(self, cfg):
        det = TrendDetectors()
        # 9 below 20 → no event (first observation, no edge)
        det.evaluate(make_ctx(cfg, snapshot=make_snapshot(ema=ema({9: 100, 20: 110, 50: 120}))))
        # 9 crosses above 20 → exactly one EMA_CROSS for 9/20
        evs = det.evaluate(make_ctx(cfg, snapshot=make_snapshot(ema=ema({9: 115, 20: 110, 50: 120}))))
        crosses = [e for e in evs if e.event_type == EventType.EMA_CROSS and e.payload["fast"] == 9
                   and e.payload["slow"] == 20]
        assert len(crosses) == 1
        # staying above → no repeat
        evs2 = det.evaluate(make_ctx(cfg, snapshot=make_snapshot(ema=ema({9: 116, 20: 110, 50: 120}))))
        assert not [e for e in evs2 if e.event_type == EventType.EMA_CROSS and e.payload["fast"] == 9]

    def test_supertrend_flip(self, cfg):
        det = TrendDetectors()
        det.evaluate(make_ctx(cfg, supertrend=SimpleNamespace(direction=1)))
        evs = det.evaluate(make_ctx(cfg, supertrend=SimpleNamespace(direction=-1)))
        assert any(e.event_type == EventType.SUPERTREND_FLIP for e in evs)

    def test_psar_flip(self, cfg):
        det = TrendDetectors()
        det.evaluate(make_ctx(cfg, snapshot=make_snapshot(psar=SimpleNamespace(direction=-1, sar=23900))))
        evs = det.evaluate(make_ctx(cfg, snapshot=make_snapshot(psar=SimpleNamespace(direction=1, sar=23800))))
        assert any(e.event_type == EventType.PSAR_FLIP for e in evs)

    def test_missing_family_no_raise(self, cfg):
        det = TrendDetectors()
        # empty snapshot, no ml → no events, no exception
        assert det.evaluate(make_ctx(cfg, snapshot=make_snapshot())) == []


class TestLevels:
    def test_watch_level_cross(self, cfg):
        det = LevelDetectors()
        det.evaluate(make_ctx(cfg, c=23990, snapshot=make_snapshot()))
        evs = det.evaluate(make_ctx(cfg, c=24010, snapshot=make_snapshot()))
        assert any(e.event_type == EventType.PRICE_LEVEL_CROSS for e in evs)

    def test_confluence_zone(self, cfg):
        det = LevelDetectors()
        # period levels PDH + an EMA50 + a pivot all near 24000 within band
        snap = make_snapshot(
            period_levels=SimpleNamespace(pdh=24005, pdl=23000, pwh=None, pwl=None, pmh=None, pml=None),
            ema=ema({50: 23995}),
            pivots=SimpleNamespace(pp=24010, r1=0, r2=0, r3=0, s1=0, s2=0, s3=0,
                                   cam_r3=0, cam_r4=0, cam_s3=0, cam_s4=0),
            vwap=None, fib_levels=None, fvg=None,
        )
        evs = det.evaluate(make_ctx(cfg, c=24000, snapshot=snap))
        conf = [e for e in evs if e.event_type == EventType.CONFLUENCE_ZONE]
        assert conf and conf[0].payload["count"] >= 2


    def test_warehouse_levels_override_snapshot(self, cfg):
        from pdp.events.detectors.levels import collect_levels

        # Snapshot has a stale CAM_R4 / PDH; warehouse (matrix source) has the correct ones.
        snap = make_snapshot(
            period_levels=SimpleNamespace(pdh=99999, pdl=1, pwh=None, pwl=None, pmh=None, pml=None),
            pivots=SimpleNamespace(pp=0, r1=0, r2=0, r3=0, s1=0, s2=0, s3=0,
                                   cam_r3=0, cam_r4=88888, cam_s3=0, cam_s4=0),
            vwap=None, fib_levels=None, fvg=None, ema=None,
        )
        wh = [("PDH", 24300.0), ("CAM_R4", 24450.0)]
        levels = dict(collect_levels(make_ctx(cfg, snapshot=snap, warehouse_levels=wh)))
        # Warehouse wins for the overlapping labels; stale snapshot values are dropped.
        assert levels["PDH"] == 24300.0
        assert levels["CAM_R4"] == 24450.0
        assert 99999 not in levels.values() and 88888 not in levels.values()


class TestRangeVolume:
    def test_custom_range_break(self, cfg):
        det = RangeVolumeDetectors()
        det.evaluate(make_ctx(cfg, c=24000, snapshot=make_snapshot()))
        evs = det.evaluate(make_ctx(cfg, c=24600, snapshot=make_snapshot()))
        assert any(e.event_type == EventType.CUSTOM_RANGE_BREAK for e in evs)

    def test_level_break_uses_warehouse_camarilla(self, cfg):
        det = RangeVolumeDetectors()
        wh = [("CAM_R4", 24450.0)]
        # First bar below CAM_R4, second breaks above → one LEVEL_BREAK.
        det.evaluate(make_ctx(cfg, c=24400, snapshot=make_snapshot(), warehouse_levels=wh))
        evs = det.evaluate(make_ctx(cfg, c=24460, snapshot=make_snapshot(), warehouse_levels=wh))
        breaks = [e for e in evs if e.event_type == EventType.LEVEL_BREAK
                  and e.payload.get("level") == "CAM_R4"]
        assert len(breaks) == 1

    def test_gap_open(self, cfg):
        det = RangeVolumeDetectors()
        day1 = datetime(2026, 6, 16, 5, 0, tzinfo=UTC)
        day2 = datetime(2026, 6, 17, 5, 0, tzinfo=UTC)
        det.evaluate(make_ctx(cfg, c=24000, snapshot=make_snapshot(), bar_time=day1))
        evs = det.evaluate(make_ctx(cfg, o=24200, c=24210, snapshot=make_snapshot(), bar_time=day2))
        gaps = [e for e in evs if e.event_type == EventType.GAP_OPEN]
        assert gaps and gaps[0].payload["direction"] == "up"

    def test_volume_spike(self, cfg):
        det = RangeVolumeDetectors()
        for i in range(12):
            det.evaluate(make_ctx(cfg, volume=1000 + i * 50, snapshot=make_snapshot()))
        evs = det.evaluate(make_ctx(cfg, volume=50000, snapshot=make_snapshot()))
        assert any(e.event_type == EventType.VOLUME_SPIKE for e in evs)
