"""Unit tests for the EOD walkthrough markdown renderer.

``render_day`` is pure, so these run without a DB. They assert the properties the report
is *for* — every fill carries the index spot, the findings section is present and ranked,
a skipped strategy is stated rather than silently missing, and the same inputs render
byte-identically so a re-run after a fix diffs cleanly against the committed file.
"""
from __future__ import annotations

from datetime import date, datetime

from pdp.backtest.sim import DayResult, LegRecord, Trade
from pdp.backtest.walkthrough import (
    LiveOverlay,
    MarketContext,
    MinuteRow,
    Provenance,
    StrategySection,
    index_row,
    render_day,
)
from pdp.backtest.walkthrough_checks import Finding

TD = date(2026, 7, 21)


def _t(hh: int, mm: int) -> datetime:
    return datetime(2026, 7, 21, hh, mm)


def _market(**kw) -> MarketContext:
    base = {
        "trade_date": TD, "underlying": "NIFTY", "expiry": TD, "dte": 0,
        "lot_size": 65, "spot_open": 24_216.0, "spot_high": 24_260.0,
        "spot_low": 24_180.0, "spot_close": 24_193.0,
        "vix_open": 11.9, "vix_close": 12.1,
    }
    return MarketContext(**{**base, **kw})


def _result() -> DayResult:
    trades = [
        Trade(side="SELL", opt_type="PE", strike=24_200.0, bar_time=_t(10, 30), qty=390,
              price=71.2, nifty=24_216.0, note="entry 6L", cum_lots=6, avg_entry=71.2),
        Trade(side="BUY", opt_type="PE", strike=24_200.0, bar_time=_t(13, 5), qty=195,
              price=35.6, nifty=24_205.0, note="pct_stop_half", cum_lots=3,
              avg_entry=71.2, leg_pnl=6_942.0, day_pnl=6_942.0, commission_inr=61.0),
    ]
    legs = [LegRecord(opt_type="PE", strike=24_200.0, entry_ist=_t(10, 30),
                      exit_ist=_t(13, 5), lots=3, avg_entry=71.2, exit_px=35.6,
                      leg_pnl=6_942.0, reason="pct_stop_half")]
    return DayResult(date=TD.isoformat(), expiry=TD.isoformat(), nifty_open=24_216.0,
                     nifty_close=24_193.0, nifty_chg=-23.0, trades=trades,
                     leg_records=legs, gross_pnl=6_942.0, commission=61.0,
                     realized=6_881.0, done_reason="", nifty_bars=75)


def _prov() -> Provenance:
    return Provenance(generated_at=_t(15, 40), git_sha="abc1234",
                      configs={"strangle": "deadbeef"})


def _section(**kw) -> StrategySection:
    base = {
        "name": "Directional Strangle", "config_label": "NIFTY", "result": _result(),
        "timeline": ["**10:30** `entry` — sell 6 PE 24200"],
        "block_census": {"neutral_no_trade": (12, "09:20", "10:25")},
        "bar_table": (["Time", "Spot"], [["10:30", "24,216.00"]]),
        "minutes": [MinuteRow(ist_dt=_t(10, 30), open=24_216.0, high=24_220.0,
                              low=24_210.0, close=24_216.0,
                              legs=[("PE", 24_200.0, 71.2)], is_decision=True,
                              action="entry 6L")],
    }
    return StrategySection(**{**base, **kw})


def test_every_fill_carries_the_index_spot():
    """The old hand-written walkthrough omitted spot beside the fills. This is the fix."""
    md = render_day(_market(), [_section()], _prov())
    assert "| Time | Side | Opt | Strike | Qty | Price | Spot |" in md
    assert "24,216.00" in md and "24,205.00" in md


def test_findings_render_ranked_with_evidence():
    section = _section(findings=[
        Finding(id="F-STRADDLE", severity="medium", title="same strike",
                evidence=["both sides at 24200"], bar_refs=["10:30"]),
        Finding(id="F-AVG-DRIFT", severity="critical", title="basis moved",
                evidence=["10:30 -> 13:05"]),
    ])
    md = render_day(_market(), [section], _prov())
    assert md.index("F-STRADDLE") > md.index("## Findings")
    # Findings arrive pre-ranked from the checker; the renderer preserves that order.
    assert "`F-STRADDLE`" in md and "`F-AVG-DRIFT`" in md
    assert "both sides at 24200" in md


def test_clean_day_says_so_without_overclaiming():
    md = render_day(_market(), [_section(findings=[])], _prov())
    assert "No invariant checks tripped" in md
    # The distinction matters: consistent books are not the same as a good day.
    assert "not that the strategy" in md


def test_skipped_strategy_is_stated_not_omitted():
    skipped = StrategySection(name="Intraday Directional", config_label="NIFTY",
                              result=None, skipped="no 09:15 opening-range candle")
    md = render_day(_market(), [_section(), skipped], _prov())
    assert "Intraday Directional" in md
    assert "no 09:15 opening-range candle" in md


def test_banners_render_above_everything():
    md = render_day(_market(banners=["expiry-cadence gap"]), [_section()], _prov())
    assert md.index("expiry-cadence gap") < md.index("## Verdict")


def test_minute_detail_is_collapsed_but_present():
    md = render_day(_market(), [_section()], _prov())
    assert "<details>" in md
    assert "Every minute (1 rows)" in md


def test_live_overlay_is_optional():
    without = render_day(_market(), [_section()], _prov())
    assert "Live / paper" not in without
    with_live = render_day(_market(), [_section()], _prov(),
                           LiveOverlay(rows=[("strangle", 5_000.0, 4)]))
    assert "Live / paper" in with_live


def test_render_is_deterministic():
    """Same inputs -> byte-identical output, so a post-fix diff shows only real change."""
    a = render_day(_market(), [_section()], _prov())
    b = render_day(_market(), [_section()], _prov())
    assert a == b


def test_day_type_classification():
    assert _market(spot_open=100.0, spot_high=200.0, spot_low=99.0,
                   spot_close=199.0).day_type == "trend-up"
    assert _market(spot_open=200.0, spot_high=201.0, spot_low=100.0,
                   spot_close=101.0).day_type == "trend-down"
    assert _market(spot_open=150.0, spot_high=200.0, spot_low=100.0,
                   spot_close=152.0).day_type == "chop"


def test_index_row_links_the_report_and_names_top_findings():
    section = _section(findings=[
        Finding(id="F-AVG-DRIFT", severity="critical", title="x"),
    ])
    row = index_row(_market(), [section])
    assert "[2026-07-21](2026-07-21.md)" in row
    assert "`F-AVG-DRIFT`" in row
    assert "+6,881" in row


def test_index_row_handles_a_strategy_that_did_not_run():
    skipped = StrategySection(name="Intraday", config_label="NIFTY", result=None,
                              skipped="no data")
    row = index_row(_market(), [_section(), skipped])
    assert row.count("—") >= 1
