"""Unit tests for the pure directional-strangle bias engine.

The engine is a deterministic pure function over plain numbers, so these tests
need no fixtures: they assert per-signal votes, the score->bucket->ratio
mapping, the VIX gate, and determinism.
"""

from __future__ import annotations

from pdp.signals.bias import (
    BiasBucket,
    BiasInputs,
    BiasWeights,
    CamLevels,
    TimeframeEMA,
    score_bias,
)


def _bull_ema(price: float = 100.0) -> TimeframeEMA:
    return TimeframeEMA(price=price, ema9=99.0, ema20=98.0, ema50=97.0)


def _bear_ema(price: float = 90.0) -> TimeframeEMA:
    return TimeframeEMA(price=price, ema9=91.0, ema20=92.0, ema50=93.0)


def _all_bull_inputs() -> BiasInputs:
    """Every signal aligned bullish."""
    return BiasInputs(
        spot=100.0,
        ema_1h=_bull_ema(),
        ema_15m=_bull_ema(),
        ema_5m=_bull_ema(),
        cam_daily=CamLevels(r3=99.0, r4=99.5, s3=90.0, s4=89.5),
        cam_weekly=CamLevels(r3=98.0, r4=98.5, s3=88.0, s4=87.5),
        pdh=95.0,
        pdl=85.0,
        pwh=94.0,
        pwl=84.0,
        orb_high=97.5,
        orb_low=93.0,
        pcr=1.3,
        vix_now=12.0,
        vix_day_open=12.5,
        vix_day_high=13.0,
        vix_recent=[13.0, 12.5, 12.0],
    )


# --------------------------------------------------------------------------- #
# Per-signal votes
# --------------------------------------------------------------------------- #


def test_ema_alignment_votes():
    bull = score_bias(BiasInputs(spot=100.0, ema_1h=_bull_ema()))
    assert bull.votes["ema_1h"] == 1
    bear = score_bias(BiasInputs(spot=90.0, ema_1h=_bear_ema()))
    assert bear.votes["ema_1h"] == -1
    # price above 50 but EMAs not stacked -> neutral
    mixed = TimeframeEMA(price=100.0, ema9=97.0, ema20=99.0, ema50=96.0)
    assert score_bias(BiasInputs(spot=100.0, ema_1h=mixed)).votes["ema_1h"] == 0


def test_cam_breakout_votes():
    up = BiasInputs(spot=100.0, cam_daily=CamLevels(r3=99, r4=100, s3=90, s4=89))
    assert score_bias(up).votes["cam_daily"] == 1
    down = BiasInputs(spot=88.0, cam_daily=CamLevels(r3=99, r4=100, s3=90, s4=89))
    assert score_bias(down).votes["cam_daily"] == -1


def test_swing_votes_require_both_sides():
    above = BiasInputs(spot=100.0, pdh=95.0, pwh=96.0, pdl=80.0, pwl=79.0)
    assert score_bias(above).votes["swing"] == 1
    # above PDH but not PWH -> neutral
    partial = BiasInputs(spot=95.5, pdh=95.0, pwh=96.0, pdl=80.0, pwl=79.0)
    assert score_bias(partial).votes["swing"] == 0


def test_pcr_thresholds():
    assert score_bias(BiasInputs(spot=100.0, pcr=1.2)).votes["pcr"] == 1
    assert score_bias(BiasInputs(spot=100.0, pcr=0.8)).votes["pcr"] == -1
    assert score_bias(BiasInputs(spot=100.0, pcr=1.0)).votes["pcr"] == 0


def test_orb_votes():
    r = score_bias(BiasInputs(spot=100.0, orb_high=99.0, orb_low=95.0))
    assert r.votes["orb"] == 1
    r2 = score_bias(BiasInputs(spot=94.0, orb_high=99.0, orb_low=95.0))
    assert r2.votes["orb"] == -1


# --------------------------------------------------------------------------- #
# Bucket / ratio mapping
# --------------------------------------------------------------------------- #


def test_all_bull_is_complete_bull_ratio():
    r = score_bias(_all_bull_inputs())
    assert r.score >= 0.75
    assert r.bucket is BiasBucket.COMPLETE_BULL
    assert (r.pe_lots, r.ce_lots) == (5, 0)


def test_all_bear_is_complete_bear_ratio():
    bear = BiasInputs(
        spot=80.0,
        ema_1h=_bear_ema(80.0),
        ema_15m=_bear_ema(80.0),
        ema_5m=_bear_ema(80.0),
        cam_daily=CamLevels(r3=95, r4=96, s3=85, s4=84),
        cam_weekly=CamLevels(r3=94, r4=95, s3=84, s4=83),
        pdh=90,
        pdl=86,
        pwh=91,
        pwl=85,
        orb_high=89,
        orb_low=86,
        pcr=0.7,
        vix_now=12.0,
        vix_day_open=12.5,
        vix_day_high=13.0,
        vix_recent=[13.0, 12.5, 12.0],
    )
    r = score_bias(bear)
    assert r.score <= -0.75
    assert r.bucket is BiasBucket.COMPLETE_BEAR
    assert (r.pe_lots, r.ce_lots) == (0, 5)


def test_conflicting_inputs_are_neutral():
    # Two equal-weight signals that cancel: PCR bullish (pcr>1.1, +1*1.0) and
    # ORB bearish (spot<orb_low, -1*1.0) -> net score 0 -> neutral.
    inp = BiasInputs(spot=100.0, pcr=1.3, orb_high=102.0, orb_low=101.0)
    r = score_bias(inp)
    assert r.votes == {"pcr": 1, "orb": -1}
    assert r.score == 0.0
    assert r.bucket is BiasBucket.NEUTRAL
    assert (r.pe_lots, r.ce_lots) == (1, 1)


def test_score_always_in_range_with_partial_data():
    r = score_bias(BiasInputs(spot=100.0, pcr=1.3))
    assert -1.0 <= r.score <= 1.0
    # only one signal present and bullish -> full +1
    assert r.score == 1.0


# --------------------------------------------------------------------------- #
# VIX gate
# --------------------------------------------------------------------------- #


def test_vix_spike_gates_entry():
    inp = _all_bull_inputs()
    inp.vix_now = 12.0
    inp.vix_day_high = 14.0
    inp.vix_day_open = 12.0  # +16.7% -> spike
    r = score_bias(inp)
    assert r.gated is True
    assert "vix_spike" in r.reason


def test_vix_at_day_high_gates_entry():
    inp = _all_bull_inputs()
    inp.vix_now = 13.0
    inp.vix_day_open = 12.8
    inp.vix_day_high = 13.0  # now == high
    r = score_bias(inp)
    assert r.gated is True
    assert "day_high" in r.reason


def test_vix_rising_last_3_gates_entry():
    inp = _all_bull_inputs()
    inp.vix_now = 12.0
    inp.vix_day_open = 12.5
    inp.vix_day_high = 13.0
    inp.vix_recent = [11.0, 11.5, 12.0]  # rising
    r = score_bias(inp)
    assert r.gated is True
    assert "rising" in r.reason


def test_stable_vix_allows_entry():
    r = score_bias(_all_bull_inputs())  # vix flat-to-down, not at high
    assert r.gated is False


def test_missing_vix_allows_entry():
    inp = _all_bull_inputs()
    inp.vix_now = None
    r = score_bias(inp)
    assert r.gated is False
    assert "vix_unavailable" in r.reason


# --------------------------------------------------------------------------- #
# Determinism & tuning
# --------------------------------------------------------------------------- #


def test_determinism():
    inp = _all_bull_inputs()
    assert score_bias(inp) == score_bias(inp)


def test_weights_are_tunable():
    inp = BiasInputs(spot=100.0, ema_1h=_bull_ema(), pcr=0.8)
    # default: ema_1h weight 2.0 (+1), pcr 1.0 (-1) -> (2-1)/3 = +0.333 -> more_bull
    assert score_bias(inp).bucket is BiasBucket.MORE_BULL
    # crank pcr weight so the bearish pcr dominates
    w = BiasWeights(w_pcr=10.0)
    assert score_bias(inp, weights=w).score < 0


# --------------------------------------------------------------------------- #
# Vote breakdown (bias-input-completeness task 6.1/1.9)
# --------------------------------------------------------------------------- #


def test_breakdown_records_abstention_for_null_input():
    """An input with no data (e.g. cam_weekly=None) is recorded as abstaining in
    the breakdown, with its configured weight, rather than simply omitted."""
    inp = BiasInputs(spot=100.0, ema_1h=_bull_ema())  # cam_weekly, pcr, etc. all None
    r = score_bias(inp)

    assert "cam_weekly" in r.breakdown
    assert r.breakdown["cam_weekly"].abstained is True
    assert r.breakdown["cam_weekly"].vote is None
    assert r.breakdown["cam_weekly"].weight == BiasWeights().w_cam_weekly


def test_breakdown_records_vote_for_present_input():
    inp = BiasInputs(spot=100.0, ema_1h=_bull_ema())
    r = score_bias(inp)

    assert r.breakdown["ema_1h"].abstained is False
    assert r.breakdown["ema_1h"].vote == 1
    assert r.breakdown["ema_1h"].weight == BiasWeights().w_ema_1h


def test_breakdown_covers_every_input_every_evaluation():
    """Every evaluation's breakdown names all eight inputs, regardless of which abstain."""
    r = score_bias(BiasInputs(spot=100.0))
    assert set(r.breakdown) == {
        "ema_1h", "ema_15m", "ema_5m", "cam_daily", "cam_weekly", "swing", "orb", "pcr",
    }
    assert all(v.abstained for v in r.breakdown.values())
