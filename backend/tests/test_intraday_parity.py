"""Live/backtest parity for the intraday directional strategy.

`pdp.signals.intraday_directional` is a pure core both paths call, so they cannot
disagree about *logic*. What they can still disagree about is the **inputs** they hand
it — and that is precisely where this repo has been bitten before (indicator warmup
depth, session anchoring, bar timestamp conventions; see `memory/live_backtest_parity.md`).

This test drives one synthetic trading day through both input builders — the real
`pdp.backtest.intraday_loader.build_intraday_day` and the real
`IntradayDirectional.on_bar`/`_build_inputs` — and asserts the resulting `IntradayInputs`
are field-for-field identical at every decision bar, then that the signal sequence the
core produces from them is identical too.

The indicator fields (EMA 9/20, SuperTrend 10/2) are supplied to the live path by a stub
that replays the *same tracker classes over the same resampled bars* the loader uses, so
an equality failure means a genuine seam bug (windowing, staleness, `prev` semantics),
not a stubbing artefact.
"""
from __future__ import annotations

import math
from dataclasses import fields as dataclass_fields
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.backtest.day_loader import WindowData, _resample_spot_ist
from pdp.backtest.intraday_config import IntradayDirectionalConfig
from pdp.backtest.intraday_loader import build_intraday_day
from pdp.indicators.ema import EMATracker
from pdp.indicators.supertrend import SuperTrendTracker
from pdp.signals.intraday_directional import (
    IntradayState,
    evaluate_entry,
    evaluate_exit,
    update_sustained_trackers,
)
from pdp.strategies.intraday_directional import IntradayDirectional

_IST_OFFSET = timedelta(hours=5, minutes=30)
_TRADE_DAY = date(2026, 6, 2)
_PRIOR_DAYS = [date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29)]
_SESSION_MINUTES = 375  # 09:15 -> 15:29 inclusive


def _utc(d: date, hh: int, mm: int) -> datetime:
    return (datetime(d.year, d.month, d.day, hh, mm) - _IST_OFFSET).replace(tzinfo=UTC)


def _synthetic_session(d: date, *, base: float, seed: int) -> list[dict]:
    """One session of 1m spot bars with enough shape to flip EMAs and SuperTrend.

    Deterministic (no RNG): a slow sine plus a linear drift, so the day trends *and*
    oscillates and the entry/exit gates actually toggle rather than sitting on one side.
    """
    bars: list[dict] = []
    for i in range(_SESSION_MINUTES):
        t = _utc(d, 9, 15) + timedelta(minutes=i)
        mid = base + 40.0 * math.sin((i + seed * 37) / 33.0) + i * 0.12
        bars.append({
            "ts": t,
            "open": round(mid - 1.5, 2),
            "high": round(mid + 4.0, 2),
            "low": round(mid - 4.0, 2),
            "close": round(mid + 1.0, 2),
            "volume": 0,
        })
    return bars


def _window() -> WindowData:
    by_day = {
        d: _synthetic_session(d, base=24000.0 + 30 * i, seed=i)
        for i, d in enumerate([*_PRIOR_DAYS, _TRADE_DAY])
    }
    return WindowData(
        spot_1m_by_day=by_day,
        chain_1m={(_TRADE_DAY, "CE"): {}, (_TRADE_DAY, "PE"): {}},
        expiry_by_day={_TRADE_DAY: date(2026, 6, 2)},
        valid_days=[_TRADE_DAY],
    )


def _prior_session_pivots(window: WindowData):
    """The daily pivot state the live engine would hold on the trade day.

    `IndicatorEngine._compute_pivots` derives the Camarilla band from the prior session's
    high/low/close through `pivots.camarilla_levels` — the same call
    `intraday_loader._daily_camarilla` makes. Reproducing that here (rather than reading
    the loader's answer) keeps the comparison honest.
    """
    from pdp.indicators.pivots import camarilla_levels

    prior = window.spot_1m_by_day[_PRIOR_DAYS[-1]]
    r3, r4, s3, s4 = camarilla_levels(
        max(b["high"] for b in prior),
        min(b["low"] for b in prior),
        prior[-1]["close"],
    )
    return SimpleNamespace(cam_r3=r3, cam_r4=r4, cam_s3=s3, cam_s4=s4)


class _ReplayIndicators:
    """Stands in for `IndicatorEngine` on the live path.

    Replays `EMATracker` / `SuperTrendTracker` over the resampled series with the same
    warmup prefix `intraday_loader` uses, and answers `ema()` / `supertrend_variants()`
    with the state as of the last bar the strategy has been handed. That is what the real
    engine does — it is updated by the same bar stream — so the stub reproduces the
    contract, not the loader's answers.
    """

    def __init__(self, window: WindowData, cfg: IntradayDirectionalConfig) -> None:
        self._cfg = cfg
        self._state: dict[tuple[str, str], dict] = {}
        self._pivots = _prior_session_pivots(window)
        warm1: list[dict] = []
        for d in _PRIOR_DAYS:
            warm1.extend(window.spot_1m_by_day[d])
        for tf in (cfg.timeframe_min, cfg.confirm_timeframe_min):
            key = ("13", f"{tf}m")
            ema = EMATracker(periods=[cfg.ema_fast, cfg.ema_slow])
            st = SuperTrendTracker(cfg.st_period, cfg.st_mult)
            for wb in _resample_spot_ist(warm1, tf):
                ema.update(wb["high"], wb["low"], wb["close"], 0.0, wb["ts"])
                st.update(wb["high"], wb["low"], wb["close"], wb["ts"])
            self._state[key] = {"ema": ema, "st": st, "ema_val": None, "st_val": None}

    def feed(self, tf: str, bar) -> None:
        s = self._state.get(("13", tf))
        if s is None:
            return
        h, lo, c = float(bar.high), float(bar.low), float(bar.close)
        s["ema_val"] = s["ema"].update(h, lo, c, 0.0, bar.bar_time)
        s["st_val"] = s["st"].update(h, lo, c, bar.bar_time)

    def ema(self, sid: str, tf: str):
        s = self._state.get((sid, tf))
        return s["ema_val"] if s else None

    def supertrend_variants(self, sid: str, tf: str):
        s = self._state.get((sid, tf))
        if s is None or s["st_val"] is None:
            return {}
        return {"st_10_2": s["st_val"]}

    def pivots(self, sid: str, tf: str):
        return self._pivots

    def supertrend(self, sid: str, tf: str):
        raise AssertionError("the strategy must read st_10_2 from supertrend_variants")


def _bar(tf: str, doc: dict):
    return SimpleNamespace(
        security_id="13", timeframe=tf, bar_time=doc["ts"],
        open=doc["open"], high=doc["high"], low=doc["low"], close=doc["close"],
    )


async def _build_live(cfg: IntradayDirectionalConfig, window: WindowData):
    s = IntradayDirectional()
    s.strategy_id = "intraday_directional_nifty"
    s.params = {
        "underlying": cfg.underlying,
        "timeframe_min": cfg.timeframe_min,
        "confirm_timeframe_min": cfg.confirm_timeframe_min,
        "orb_start_ist": cfg.orb_start_ist.strftime("%H:%M"),
        "orb_minutes": cfg.orb_minutes,
        "initial_lots": cfg.initial_lots,
        "max_lots": cfg.max_lots,
        "entry_after_ist": cfg.entry_after_ist.strftime("%H:%M"),
        "squareoff_ist": cfg.squareoff_ist.strftime("%H:%M"),
    }
    s._mode = "paper"
    s._slog = None
    ind = _ReplayIndicators(window, cfg)
    ctx = SimpleNamespace(
        params=s.params, watchlist=[], log=MagicMock(), indicators=ind, market=None,
        orders=SimpleNamespace(get_realized_pnl=AsyncMock(return_value=0)),
        session_maker=None, chain_hub=None, option_bars_col=None, _event_service=None,
    )
    ctx.emit_critical = MagicMock()
    await s.on_init(ctx)
    s._reconcile_task.cancel()
    s._option_st_enabled = False  # no option bars on either side of this comparison
    s._dte_max = None
    return s, ind


async def _live_inputs(cfg: IntradayDirectionalConfig, window: WindowData) -> list:
    """Replay the day through `on_bar` and capture every `IntradayInputs` it builds.

    Bars are delivered in the order a live host would: every 1m bar of a bucket, then the
    higher-timeframe bars that close with it — confirmation timeframe **before** the
    decision timeframe, the order that makes the opening range visible earliest and so
    the harshest ordering for parity.
    """
    s, ind = await _build_live(cfg, window)
    raw1 = window.spot_1m_by_day[_TRADE_DAY]
    dec = {b["ts"]: b for b in _resample_spot_ist(raw1, cfg.timeframe_min)}
    conf = {b["ts"]: b for b in _resample_spot_ist(raw1, cfg.confirm_timeframe_min)}

    captured: list = []
    original = s._build_inputs

    async def _spy(ist, bar, spot):
        inp = await original(ist, bar, spot)
        captured.append(inp)
        return inp

    s._build_inputs = _spy  # type: ignore[method-assign]

    dec_tf = f"{cfg.timeframe_min}m"
    conf_tf = f"{cfg.confirm_timeframe_min}m"
    for doc in raw1:
        await s.on_bar(_bar("1m", doc))
        closes_at = doc["ts"] + timedelta(minutes=1)
        c_doc = conf.get(closes_at - timedelta(minutes=cfg.confirm_timeframe_min))
        if c_doc is not None:
            ind.feed(conf_tf, _bar(conf_tf, c_doc))
            await s.on_bar(_bar(conf_tf, c_doc))
        d_doc = dec.get(closes_at - timedelta(minutes=cfg.timeframe_min))
        if d_doc is not None:
            ind.feed(dec_tf, _bar(dec_tf, d_doc))
            await s.on_bar(_bar(dec_tf, d_doc))
    return captured


@pytest.fixture
def cfg() -> IntradayDirectionalConfig:
    return IntradayDirectionalConfig(underlying="NIFTY")


@pytest.fixture
def window() -> WindowData:
    return _window()


@pytest.mark.asyncio
async def test_both_paths_build_the_same_decision_bars(cfg, window) -> None:
    """Same day, same bars — the two builders must agree on which bars are decisions.

    The live path stops building inputs once the session is closed out, so its series is
    a *prefix* of the loader's: the loader keeps emitting post-square-off bars that the
    engine then ignores. The prefix must line up exactly, and end on square-off.
    """
    day = build_intraday_day(window, cfg, _TRADE_DAY)
    assert day is not None
    live = await _live_inputs(cfg, window)

    assert len(day.decision_bars) == _SESSION_MINUTES // cfg.timeframe_min
    bt_times = [b.ist_dt for b in day.decision_bars]
    assert bt_times[: len(live)] == [i.ist_dt for i in live]
    assert live[-1].ist_dt.time() == cfg.squareoff_ist, (
        "live stopped somewhere other than square-off"
    )


@pytest.mark.asyncio
async def test_inputs_are_field_for_field_identical(cfg, window) -> None:
    """Every field of `IntradayInputs` the two paths independently derive must match.

    `option_st_dir` is excluded: it depends on which strike is actually held, which is
    the engine's decision rather than a market input, and each path resolves it against
    that strike's own bars.
    """
    day = build_intraday_day(window, cfg, _TRADE_DAY)
    assert day is not None
    live = await _live_inputs(cfg, window)

    skip = {"option_st_dir"}
    names = [f.name for f in dataclass_fields(live[0]) if f.name not in skip]

    mismatches: list[str] = []
    for bt_bar, lv in zip(day.decision_bars[: len(live)], live, strict=True):
        for name in names:
            a = getattr(bt_bar.inputs, name)
            b = getattr(lv, name)
            same = (
                a == b if not isinstance(a, float) or not isinstance(b, float)
                else a == pytest.approx(b, rel=1e-9)
            )
            if not same:
                mismatches.append(f"{bt_bar.ist_dt} {name}: backtest={a!r} live={b!r}")

    assert not mismatches, "live/backtest input drift:\n" + "\n".join(mismatches[:20])


@pytest.mark.asyncio
async def test_opening_range_becomes_visible_on_the_same_bar(cfg, window) -> None:
    """The ORB candle and the decision bar before it close at the same instant, and
    inter-timeframe delivery order is not guaranteed live. Both paths must gate on the
    clock, so the range appears on the 09:30 bar and not the 09:25 one."""
    day = build_intraday_day(window, cfg, _TRADE_DAY)
    assert day is not None
    live = await _live_inputs(cfg, window)

    by_time = {i.ist_dt.time(): i for i in live}
    bt_by_time = {b.ist_dt.time(): b.inputs for b in day.decision_bars}

    from datetime import time as _t

    assert by_time[_t(9, 25)].orb_high is None
    assert bt_by_time[_t(9, 25)].orb_high is None
    assert by_time[_t(9, 30)].orb_high is not None
    assert by_time[_t(9, 30)].orb_high == bt_by_time[_t(9, 30)].orb_high
    assert by_time[_t(9, 30)].orb_low == bt_by_time[_t(9, 30)].orb_low
    # And it is the 09:15-09:29 range, not some later window.
    assert day.orb_high == max(
        float(b["high"]) for b in window.spot_1m_by_day[_TRADE_DAY][:15]
    )


def test_confirmation_timeframe_is_never_read_before_its_bar_closes(cfg, window) -> None:
    """No look-ahead on the 15m confirmation series.

    A confirmation bar stamped T covers T..T+15 and does not exist until T+15. Indexing
    it at T would let the 09:15 decision bar consult a candle containing the next 15
    minutes of price — and `require_15m_confirm` gates entry on exactly those fields.
    """
    day = build_intraday_day(window, cfg, _TRADE_DAY)
    assert day is not None
    from datetime import time as _t

    by_time = {b.ist_dt.time(): b.inputs for b in day.decision_bars}

    # Nothing before the first confirmation bar closes (09:30) may have a 15m read.
    for hh, mm in ((9, 15), (9, 20), (9, 25)):
        inp = by_time[_t(hh, mm)]
        assert inp.ema9_15m is None
        assert inp.ema20_15m is None
        assert inp.st_15m_dir is None

    # From 09:30 the 09:15-09:29 candle has closed and becomes readable.
    assert by_time[_t(9, 30)].st_15m_dir is not None
    # ...and it stays the 09:15 candle's value until the 09:30 candle closes at 09:45.
    assert by_time[_t(9, 40)].ema9_15m == by_time[_t(9, 30)].ema9_15m
    assert by_time[_t(9, 45)].ema9_15m != by_time[_t(9, 30)].ema9_15m


@pytest.mark.asyncio
async def test_session_vwap_matches_bar_for_bar(cfg, window) -> None:
    """The spot index has no volume, so both paths use the same session-anchored mean of
    typical price over 1m bars. A different anchor or cutoff would show up here."""
    day = build_intraday_day(window, cfg, _TRADE_DAY)
    assert day is not None
    live = await _live_inputs(cfg, window)

    for bt_bar, lv in zip(day.decision_bars[: len(live)], live, strict=True):
        assert lv.session_vwap == pytest.approx(bt_bar.inputs.session_vwap, rel=1e-12)

    # The first decision bar's VWAP is the mean over exactly its own 1m bars.
    raw1 = window.spot_1m_by_day[_TRADE_DAY][: cfg.timeframe_min]
    expected = sum(
        (b["high"] + b["low"] + b["close"]) / 3.0 for b in raw1
    ) / len(raw1)
    assert live[0].session_vwap == pytest.approx(expected)


@pytest.mark.asyncio
async def test_signal_sequence_is_identical(cfg, window) -> None:
    """The end-to-end guarantee: identical inputs replayed through the shared core with
    identical state produce the identical decision sequence on both paths."""
    day = build_intraday_day(window, cfg, _TRADE_DAY)
    assert day is not None
    live = await _live_inputs(cfg, window)
    params = cfg.to_params()

    def _replay(inputs: list) -> list[tuple]:
        state = IntradayState()
        out: list[tuple] = []
        for inp in inputs:
            update_sustained_trackers(inp, params, state)
            ex = evaluate_exit(inp, params, state, ltp=None, day_pnl=0.0)
            if ex is not None:
                out.append((inp.ist_dt, "exit", ex.reason.value))
                state.on_exit(inp.ist_dt, ex.reason)
                continue
            sig, block, _conds = evaluate_entry(inp, params, state)
            if sig is not None:
                out.append((inp.ist_dt, "entry", sig.side.value))
                state.on_open(sig.side, sig.lots, 100.0, 24000.0, inp.ist_dt)
            else:
                out.append((inp.ist_dt, "blocked", str(block)))
        return out

    bt_seq = _replay([b.inputs for b in day.decision_bars])
    live_seq = _replay(live)

    # The live series stops at square-off; over the bars it did evaluate, every single
    # decision — entry side, exit reason, and the reason each blocked bar was blocked —
    # must be the same one the backtest reached.
    assert bt_seq[: len(live_seq)] == live_seq
    # A day that never decided anything would make this test vacuous.
    assert any(kind == "entry" for _t, kind, _d in bt_seq), (
        "synthetic day produced no entry — the parity assertion would be vacuous"
    )


def test_camarilla_math_is_shared(window) -> None:
    """Both paths must land on the same Camarilla numbers. The loader derives them from
    the prior session's HLC via `pivots.camarilla_levels`; the live engine's daily pivot
    state is built by `_compute_pivots`, which calls that same function — so proving the
    one function is the only source is what keeps them equal."""
    from pdp.indicators.pivots import camarilla_levels

    prior = window.spot_1m_by_day[_PRIOR_DAYS[-1]]
    high = max(b["high"] for b in prior)
    low = min(b["low"] for b in prior)
    close = prior[-1]["close"]

    r3, r4, s3, s4 = camarilla_levels(high, low, close)
    rng = high - low
    assert r4 == pytest.approx(close + rng * 1.1 / 2)
    assert s4 == pytest.approx(close - rng * 1.1 / 2)
    assert r3 == pytest.approx(close + rng * 1.1 / 4)
    assert s3 == pytest.approx(close - rng * 1.1 / 4)
