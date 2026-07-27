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
    SeriesInputs,
    TimeframeEMA,
    _atm_vote,
    _psar_vote,
    _series_trend,
    _st_vote,
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
        # st_1h agreeing-bullish so the two-family extreme guard permits COMPLETE_BULL
        # (weight defaults 0.0, so it drives the guard without shifting the score).
        st_1h=(1, 1),
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
        st_1h=(-1, -1),  # agreeing-bearish 1h SuperTrend permits COMPLETE_BEAR
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


# The gate is OFF by default (`BiasWeights.vix_gate_enabled`) and that flag is the one
# switch every caller reads. These tests arm it explicitly rather than leaning on a default.
_VIX_ON = BiasWeights(vix_gate_enabled=True)


def test_vix_spike_gates_entry():
    inp = _all_bull_inputs()
    inp.vix_now = 12.0
    inp.vix_day_high = 14.0
    inp.vix_day_open = 12.0  # +16.7% -> spike
    r = score_bias(inp, _VIX_ON)
    assert r.gated is True
    assert "vix_spike" in r.reason


def test_vix_at_day_high_gates_entry():
    inp = _all_bull_inputs()
    inp.vix_now = 13.0
    inp.vix_day_open = 12.8
    inp.vix_day_high = 13.0  # now == high
    r = score_bias(inp, _VIX_ON)
    assert r.gated is True
    assert "day_high" in r.reason


def test_vix_rising_last_3_gates_entry():
    inp = _all_bull_inputs()
    inp.vix_now = 12.0
    inp.vix_day_open = 12.5
    inp.vix_day_high = 13.0
    inp.vix_recent = [11.0, 11.5, 12.0]  # rising
    r = score_bias(inp, _VIX_ON)
    assert r.gated is True
    assert "rising" in r.reason


def test_stable_vix_allows_entry():
    r = score_bias(_all_bull_inputs(), _VIX_ON)  # vix flat-to-down, not at high
    assert r.gated is False


def test_missing_vix_allows_entry():
    inp = _all_bull_inputs()
    inp.vix_now = None
    r = score_bias(inp, _VIX_ON)
    assert r.gated is False
    assert "vix_unavailable" in r.reason


def test_gate_disabled_by_default():
    """Default weights never gate, whatever the VIX data says."""
    inp = _all_bull_inputs()
    inp.vix_now = 12.0
    inp.vix_day_high = 14.0
    inp.vix_day_open = 12.0  # would be a spike if the gate were armed
    r = score_bias(inp)
    assert r.gated is False
    assert "vix_gate_disabled" in r.reason


def test_disabled_gate_ignores_vix_inputs_entirely():
    """With the gate off, supplying VIX and withholding it must be indistinguishable.

    This is the invariant that lets every caller (live strategy, strangle_run,
    strangle_walkforward, sweep_engine, replay) keep VIX populated for *reporting*
    instead of nulling it out to emulate "gate off" -- which is exactly how three
    backtest entry points ended up silently gating against configs that asked for it off.
    """
    with_vix = _all_bull_inputs()
    with_vix.vix_now = 12.0
    with_vix.vix_day_open = 12.0
    with_vix.vix_day_high = 14.0
    with_vix.vix_recent = [11.0, 11.5, 12.0]

    without_vix = _all_bull_inputs()
    without_vix.vix_now = None
    without_vix.vix_day_open = None
    without_vix.vix_day_high = None
    without_vix.vix_recent = []

    a, b = score_bias(with_vix), score_bias(without_vix)
    assert a.gated is False and b.gated is False
    assert (a.score, a.bucket, a.pe_lots, a.ce_lots) == (b.score, b.bucket, b.pe_lots, b.ce_lots)


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
    """Every evaluation's breakdown names all fifteen inputs, regardless of which abstain."""
    r = score_bias(BiasInputs(spot=100.0))
    assert set(r.breakdown) == {
        "ema_1h", "ema_15m", "ema_5m", "cam_daily", "cam_weekly", "swing", "orb", "pcr",
        "st_5m", "st_15m", "st_1h", "psar_5m", "psar_15m", "psar_1h", "atm",
    }
    assert all(v.abstained for v in r.breakdown.values())


# --------------------------------------------------------------------------- #
# Quorum floor + extreme-bucket guard (bias-ranking-hardening)
# --------------------------------------------------------------------------- #


def test_quorum_floor_forces_neutral_when_starved():
    """The proven 2026-07-21 failure: only ORB+PCR present (both bearish) renormalises to
    score -1.0, but 2.0/10.5 = 0.19 is below the quorum floor -> forced NEUTRAL, not a naked
    COMPLETE_BEAR."""
    inp = BiasInputs(spot=100.0, orb_high=101.0, orb_low=100.5, pcr=0.7)  # spot<orb_low -> -1; pcr<0.9 -> -1
    r = score_bias(inp)
    assert r.votes == {"orb": -1, "pcr": -1}
    assert r.score == -1.0  # raw renormalised score still saturates
    assert r.present_weight_frac < BiasWeights().min_quorum_weight_frac
    assert r.bucket is BiasBucket.NEUTRAL  # ...but quorum forces neutral
    assert (r.pe_lots, r.ce_lots) == (1, 1)


def test_quorum_reports_present_weight_fraction():
    r_full = score_bias(_all_bull_inputs())
    assert r_full.present_weight_frac == 1.0
    assert "quorum=1.00" in r_full.reason
    # ema_1h(2.0)+pcr(1.0) = 3.0/10.5 = 0.286 -> above the floor, scores normally
    r_partial = score_bias(BiasInputs(spot=100.0, ema_1h=_bull_ema(), pcr=1.3))
    assert abs(r_partial.present_weight_frac - 3.0 / 10.5) < 1e-9
    assert r_partial.bucket is not BiasBucket.NEUTRAL


def test_extreme_bucket_downgraded_without_agreeing_trend():
    """A score in the COMPLETE_BEAR band but with ema_1h abstaining downgrades to the defended
    MOST_BEAR (keeps a protective PE side) rather than selling naked 0:5."""
    # Bearish set that clears quorum and the -0.75 threshold, but ema_1h is absent.
    inp = BiasInputs(
        spot=80.0,
        ema_15m=_bear_ema(80.0),
        ema_5m=_bear_ema(80.0),
        cam_daily=CamLevels(r3=95, r4=96, s3=85, s4=84),
        cam_weekly=CamLevels(r3=94, r4=95, s3=84, s4=83),
        pdh=90, pdl=86, pwh=91, pwl=85,
        orb_high=89, orb_low=86,
        pcr=0.7,
    )
    r = score_bias(inp)
    assert r.score <= -0.75
    assert r.breakdown["ema_1h"].abstained is True
    assert r.bucket is BiasBucket.MOST_BEAR
    assert (r.pe_lots, r.ce_lots) == (2, 4)


def test_extreme_bucket_allowed_with_agreeing_trend():
    """The full bull/bear sets (ema_1h present and agreeing) still reach the naked buckets."""
    bull = score_bias(_all_bull_inputs())
    assert bull.bucket is BiasBucket.COMPLETE_BULL
    assert (bull.pe_lots, bull.ce_lots) == (5, 0)


def test_extreme_bull_downgraded_when_trend_disagrees():
    """If the score still reaches the COMPLETE_BULL band but ema_1h is bearish, downgrade to the
    defended MOST_BULL. (A light ema_1h weight keeps the score complete while the vote disagrees,
    isolating the guard from the score-lowering effect of a heavy disagreeing vote.)"""
    inp = _all_bull_inputs()
    inp.ema_1h = _bear_ema()  # its own bar close (90) is below the stack -> vote -1
    w = BiasWeights(w_ema_1h=0.5)  # 8.0/9.0 = 0.889 -> still COMPLETE_BULL band
    r = score_bias(inp, weights=w)
    assert r.score >= 0.75
    assert r.breakdown["ema_1h"].vote == -1
    assert r.bucket is BiasBucket.MOST_BULL
    assert (r.pe_lots, r.ce_lots) == (4, 2)


# --------------------------------------------------------------------------- #
# Multi-signal votes: SuperTrend / PSAR / ATM (bias-ranking-multisignal)
# --------------------------------------------------------------------------- #


def test_st_vote_agreement_table():
    """Agreement of both (10,2) and (10,3) variants required for a directional ST vote."""
    assert _st_vote((1, 1)) == 1
    assert _st_vote((-1, -1)) == -1
    assert _st_vote((1, -1)) == 0  # disagree -> weight, no direction
    assert _st_vote((-1, 1)) == 0
    assert _st_vote(None) is None  # unseeded -> abstain


def test_psar_vote_direction():
    assert _psar_vote(1) == 1
    assert _psar_vote(-1) == -1
    assert _psar_vote(None) is None


def test_series_trend_combines_present_subreads():
    """A series' EMA/ST/PSAR sub-reads sum, and the sign is the trend; abstains only when
    the series has no data at all."""
    # EMA bullish (price>50EMA), ST bullish, PSAR bullish -> +1
    bull = SeriesInputs(ema=_bull_ema(), st=(1, 1), psar=1)
    assert _series_trend(bull) == 1
    # EMA bearish, ST bearish, PSAR bearish -> -1
    bear = SeriesInputs(ema=_bear_ema(), st=(-1, -1), psar=-1)
    assert _series_trend(bear) == -1
    # net zero (one up, one down) -> 0
    mixed = SeriesInputs(ema=_bull_ema(), psar=-1)  # +1 and -1 -> 0
    assert _series_trend(mixed) == 0
    # only one live sub-read still contributes
    assert _series_trend(SeriesInputs(psar=1)) == 1
    # nothing present -> abstain
    assert _series_trend(SeriesInputs()) is None
    assert _series_trend(None) is None


def test_atm_vote_inverts_pe_and_requires_agreement():
    ce_bull = SeriesInputs(ema=_bull_ema(), st=(1, 1), psar=1)  # CE rising -> bullish underlying
    pe_bear = SeriesInputs(ema=_bear_ema(), st=(-1, -1), psar=-1)  # PE falling -> bullish underlying
    # CE up + PE down -> both point bullish once PE is inverted -> +1
    assert _atm_vote(ce_bull, pe_bear) == 1
    # CE down + PE up -> both bearish -> -1
    assert _atm_vote(pe_bear, ce_bull) == -1
    # CE up + PE up (PE rising) -> inverted PE is bearish -> conflict -> 0
    assert _atm_vote(ce_bull, ce_bull) == 0
    # either side absent -> abstain
    assert _atm_vote(ce_bull, None) is None
    assert _atm_vote(None, pe_bear) is None


def test_new_votes_flow_through_score_when_weighted():
    """With non-zero weights the new votes participate in the weighted average and breakdown."""
    inp = BiasInputs(
        spot=100.0,
        st_1h=(1, 1),
        psar_1h=1,
        atm_ce_5m=SeriesInputs(ema=_bull_ema(), st=(1, 1), psar=1),
        atm_pe_5m=SeriesInputs(ema=_bear_ema(), st=(-1, -1), psar=-1),
    )
    w = BiasWeights(w_st_1h=1.0, w_psar_1h=1.0, w_atm=1.0)
    r = score_bias(inp, weights=w)
    assert r.votes == {"st_1h": 1, "psar_1h": 1, "atm": 1}
    assert r.score == 1.0
    assert r.breakdown["atm"].vote == 1
    assert r.breakdown["st_1h"].abstained is False


def test_new_votes_abstain_and_stay_out_of_denominator():
    """A weighted-but-absent new input abstains and is excluded from the quorum denominator,
    exactly like the original eight."""
    w = BiasWeights(w_st_1h=1.0)  # weighted but no st_1h supplied
    r = score_bias(BiasInputs(spot=100.0, pcr=1.3), weights=w)
    assert r.breakdown["st_1h"].abstained is True
    # denominator = configured non-zero weights that were present; st_1h absent so excluded
    assert r.votes == {"pcr": 1}


def test_extreme_needs_both_ema_and_st_1h():
    """The naked COMPLETE buckets now require BOTH ema_1h and st_1h present-and-agreeing."""
    # ema_1h agrees but st_1h abstains -> downgrade to defended MOST_BULL
    inp = _all_bull_inputs()
    inp.st_1h = None
    r = score_bias(inp)
    assert r.score >= 0.75
    assert r.bucket is BiasBucket.MOST_BULL
    assert (r.pe_lots, r.ce_lots) == (4, 2)

    # ema_1h agrees but st_1h disagrees (bearish) -> still downgrade
    inp2 = _all_bull_inputs()
    inp2.st_1h = (-1, -1)
    r2 = score_bias(inp2)
    assert r2.bucket is BiasBucket.MOST_BULL

    # both agree -> naked COMPLETE_BULL allowed
    r3 = score_bias(_all_bull_inputs())
    assert r3.bucket is BiasBucket.COMPLETE_BULL
