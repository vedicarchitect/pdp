from __future__ import annotations

from datetime import date

import pytest

from pdp.options.analytics import (
    classify_oi_buildup,
    compute_iv_rank_percentile,
    compute_straddle_history,
    multi_strike_oi_series,
)
from pdp.options.fii_dii import StubFIIDIISource


def test_classify_oi_buildup():
    prev = [
        {"strike": 100, "ce": {"last_price": 10, "oi": 100}, "pe": {"last_price": 10, "oi": 100}},
        {"strike": 110, "ce": {"last_price": 5, "oi": 50}, "pe": {"last_price": 15, "oi": 150}},
        {"strike": 120, "ce": {"last_price": 2, "oi": 200}, "pe": {"last_price": 20, "oi": 80}},
        {"strike": 130, "ce": {"last_price": 1, "oi": 100}, "pe": {"last_price": 25, "oi": 100}},
    ]
    
    # 100 CE: Price up, OI up -> Long Buildup
    # 100 PE: Price down, OI up -> Short Buildup
    # 110 CE: Price up, OI down -> Short Covering
    # 110 PE: Price down, OI down -> Long Unwinding
    curr = [
        {"strike": 100, "ce": {"last_price": 12, "oi": 120}, "pe": {"last_price": 8, "oi": 120}},
        {"strike": 110, "ce": {"last_price": 7, "oi": 40}, "pe": {"last_price": 12, "oi": 130}},
    ]
    
    res = classify_oi_buildup(curr, prev)
    assert len(res) == 2
    
    assert res[0]["strike"] == 100
    assert res[0]["ce"]["classification"] == "long_buildup"
    assert res[0]["pe"]["classification"] == "short_buildup"

    assert res[1]["strike"] == 110
    assert res[1]["ce"]["classification"] == "short_covering"
    assert res[1]["pe"]["classification"] == "long_unwinding"

def test_compute_straddle_history():
    snapshots = [
        {"snapshot_ts": "T1", "spot_price": 102, "strikes": [
            {"strike": 100, "ce": {"last_price": 5}, "pe": {"last_price": 3}}
        ]},
        {"snapshot_ts": "T2", "spot_price": 99, "strikes": [
            {"strike": 100, "ce": {"last_price": 3}, "pe": {"last_price": 4}}
        ]}
    ]
    
    res = compute_straddle_history(snapshots)
    assert len(res) == 2
    assert res[0]["straddle_premium"] == 8.0
    assert res[1]["straddle_premium"] == 7.0

def test_compute_iv_rank_percentile():
    # 25 historical days (>= 20 threshold) — rank/percentile should compute
    historical_ivs = [15.0, 20.0, 25.0, 30.0, 10.0] * 5  # 25 days

    res1 = compute_iv_rank_percentile(historical_ivs, current_iv=25.0)
    # low = 10, high = 30 → rank = (25-10)/(30-10) = 75%
    # below 25.0: 10,15,20 each repeated 5x = 15 out of 25 = 60%
    assert res1["iv_rank"] == 75.0
    assert res1["iv_percentile"] == 60.0
    assert res1["iv_high"] == 30.0
    assert res1["iv_low"] == 10.0
    assert res1["lookback_days"] == 25
    assert "warning" not in res1

    # Test flat IV with enough data
    res2 = compute_iv_rank_percentile([20.0] * 20, current_iv=20.0)
    assert res2["iv_rank"] == 0.0
    assert res2["iv_percentile"] == 0.0


def test_compute_iv_rank_percentile_insufficient_data():
    # < 20 days → null values + warning
    res = compute_iv_rank_percentile([15.0, 20.0, 25.0, 30.0, 10.0], current_iv=25.0)
    assert res["iv_rank"] is None
    assert res["iv_percentile"] is None
    assert res["iv_high"] is None
    assert res["iv_low"] is None
    assert "warning" in res
    assert res["lookback_days"] == 5


def test_compute_iv_rank_percentile_empty():
    res = compute_iv_rank_percentile([], current_iv=20.0)
    assert res["iv_rank"] is None
    assert res["iv_percentile"] is None
    assert "warning" in res
    assert res["lookback_days"] == 0


def _make_snap(ts: str, strikes: list[dict]) -> dict:
    return {"snapshot_ts": ts, "spot_price": 100, "strikes": strikes}


def test_multi_strike_oi_series_top_n():
    strikes_t1 = [
        {"strike": 100, "ce": {"oi": 5000}, "pe": {"oi": 4000}},
        {"strike": 105, "ce": {"oi": 3000}, "pe": {"oi": 2000}},
        {"strike": 110, "ce": {"oi": 1000}, "pe": {"oi": 1500}},
    ]
    strikes_t2 = [
        {"strike": 100, "ce": {"oi": 5500}, "pe": {"oi": 4200}},
        {"strike": 105, "ce": {"oi": 2800}, "pe": {"oi": 2200}},
        {"strike": 110, "ce": {"oi": 1100}, "pe": {"oi": 1600}},
    ]
    snaps = [_make_snap("T1", strikes_t1), _make_snap("T2", strikes_t2)]

    res = multi_strike_oi_series(snaps, top_n=2)

    # Top 2 strikes by total OI in final snapshot: 100 (9700) and 105 (5000)
    assert set(res["strikes"].keys()) == {100, 105}
    assert len(res["timestamps"]) == 2
    assert res["strikes"][100]["ce_oi"] == [5000, 5500]
    assert res["strikes"][100]["pe_oi"] == [4000, 4200]
    assert res["strikes"][105]["ce_oi"] == [3000, 2800]


def test_multi_strike_oi_series_empty():
    res = multi_strike_oi_series([])
    assert res == {"timestamps": [], "strikes": {}}


@pytest.mark.asyncio
async def test_stub_fii_dii_returns_none():
    stub = StubFIIDIISource()
    result = await stub.fetch(date.today())
    assert result is None
