# bias-ranking-multisignal

## Why

`bias-ranking-hardening` (archived 2026-07-22) made the shared bias engine
(`pdp/signals/bias.py::score_bias`) safe against abstention-saturation, but the ranking still reads
only **8 inputs**, all EMA/level/PCR based. The trend read rests on a single family (EMA 9/20/50
alignment) per timeframe. The user has directed enriching the ranking with three more signal
families so the directional lean reflects a broader trend consensus, in lockstep across backtest and
live (non-negotiable #4 — the `IndicatorEngine` already computes all three; the bias engine only
consumes them):

- **SuperTrend (10,2) + (10,3)** on 5m / 15m / 1h — **per-timeframe agreement** (both variants must
  point the same way) contributes one vote per timeframe → 3 votes.
- **Parabolic SAR** on 5m / 15m / 1h — its flip direction contributes one vote per timeframe → 3
  votes.
- **ATM option price** — the same trend read (EMA-stack + SuperTrend agreement + PSAR) applied to the
  current ATM **CE** and ATM **PE** 5m series; the PE read is inverted (a falling PE ⇒ bullish
  underlying) and combined with the CE read into **one 5m vote**.

The two paths must stay bit-identical on the new votes — the backtest loader
(`pdp/backtest/strangle_loader.py`) currently warms only EMAs, so SuperTrend / PSAR / ATM are net-new
there and must be warmed-then-replayed with the same trackers the live `IndicatorEngine` uses. The
extreme-bucket guard from `bias-ranking-hardening` (which today requires an agreeing `ema_1h`) is
extended to also require an agreeing `st_1h`, so a fully-naked directional bet needs *two*
independent higher-timeframe trend families to confirm, not one.

Once wired, the enriched ranking is benchmarked against the current baselines
(NIFTY +₹42.71L / BANKNIFTY +₹46.82L / SENSEX +₹20.87L) on a 1-week trade-by-trade run and a 5-year
run per index, and promoted only through the walk-forward PASS gate — never off a single-window win.

## What Changes

- **Three new vote families in the shared engine** (`pdp/signals/bias.py`). Extend `BiasInputs`,
  `BiasWeights`, and `score_bias` with abstention-aware votes:
  - `st_5m/st_15m/st_1h: tuple[int, int] | None` = `(dir_ST(10,2), dir_ST(10,3))`; `_st_vote(pair)`
    = `+1` if both `+1`, `-1` if both `-1`, else `0`; `None` → abstain. Weights `w_st_5m/15m/1h`.
  - `psar_5m/psar_15m/psar_1h: int | None` (`ParabolicSARState.direction`); `_psar_vote(d) = d`.
    Weights `w_psar_5m/15m/1h`.
  - `atm_ce_5m/atm_pe_5m: TimeframeEMA | None` (+ the ST/PSAR reads for each side); a reusable
    `_series_trend(...)` helper produces a per-series trend read reused by spot and by CE/PE;
    `_atm_vote = combine(read_CE, invert(read_PE))`. One weight `w_atm`.
  - New weights default to modest values and are **walk-forward tuned**, never hand-picked as final.
- **Extreme-bucket guard extended.** `_guard_extreme` requires the naked `COMPLETE_BULL/BEAR` buckets
  to have **both** `ema_1h` and `st_1h` present and agreeing; otherwise downgrade to `MOST_BULL/BEAR`.
- **Backtest wiring** (`pdp/backtest/strangle_loader.py`). Build `SuperTrendTracker(10,2)` +
  `SuperTrendTracker(10,3)` and `ParabolicSARTracker()` per timeframe, warm from the existing
  spot-warmup prefix then replay per decision bar (mirroring the current `_ema_series` /`_tf_ema_at`
  pattern). Resolve the ATM CE/PE 5m marks off the day chain per decision bar and feed their EMA/ST/
  PSAR reads. `pdp/backtest/strangle_config.py` gains the ST/PSAR/ATM knobs (`from_dict`/`to_dict`).
- **Live wiring** (`pdp/strategies/directional_strangle.py`). Add an `IndicatorReader` accessor for
  `get_supertrend_variants(sid, tf)`; ensure `supertrend`/`psar` families are configured on 5m/15m/1h;
  read `(dir_10_2, dir_10_3)` and PSAR direction per timeframe in `_build_bias_inputs`; obtain the ATM
  CE/PE 5m trend via `pdp/strategy/atm_suite.py` off the hot path. Extend `check_bias_satisfiability`
  and the readiness "Indicators" component so an unseeded ST/PSAR/ATM input blocks entry exactly as an
  unseeded EMA does today.
- **Config + watchlists.** `backtest/configs/strangle_{nifty,banknifty,sensex}_hedged.yaml` gain the
  new knobs + weights and `supertrend`/`psar` families on the 5m/15m/1h watchlist entries.
- **Benchmark evaluation.** 1-week `--trace` + 5-year runs per index; `POST /compare` new vs current;
  metrics vs baselines; walk-forward PASS before any promotion.

## Impact

- Affected specs: `bias-input-completeness` — ADD SuperTrend-vote, PSAR-vote, ATM-vote, and
  backtest↔live-parity requirements; MODIFY the naked-bucket-confirmation requirement (now needs
  `ema_1h` **and** `st_1h`) and the startup-satisfiability requirement (now covers the new families).
- Affected code: `backend/pdp/signals/bias.py` (`BiasInputs`, `BiasWeights`, `score_bias`,
  `_guard_extreme`, new `_st_vote`/`_psar_vote`/`_atm_vote`/`_series_trend`),
  `backend/pdp/backtest/strangle_loader.py` (ST/PSAR/ATM warm-then-replay + ATM mark resolution),
  `backend/pdp/backtest/strangle_config.py` (new knobs), `backend/pdp/strategies/directional_strangle.py`
  (`_build_bias_inputs`, readiness + satisfiability gating), `backend/pdp/strategy/context.py`
  (variants accessor), `backend/pdp/strategy/atm_suite.py` (reused for the live ATM read),
  `backend/backtest/configs/strangle_*_hedged.yaml`. No schema/migration changes.
- Builds directly on `bias-ranking-hardening`; the quorum floor and warmup prefix it added are
  preconditions and are unchanged here.
