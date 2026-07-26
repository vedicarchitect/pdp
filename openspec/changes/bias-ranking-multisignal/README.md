# bias-ranking-multisignal

Enrich the shared bias-ranking engine (`pdp/signals/bias.py::score_bias`) with three new
abstention-aware vote families across backtest **and** live in lockstep, then benchmark vs the
current baselines.

## What landed (engine + wiring, all tests green)

- **7 new votes** in `score_bias`, all opt-in (`BiasWeights.w_*` default `0.0` → inert in the score
  and out of the quorum denominator until a config sets them):
  - **SuperTrend agreement** `st_5m/st_15m/st_1h` — `(dir_ST(10,2), dir_ST(10,3))`; `+1` iff both
    variants bullish, `-1` iff both bearish, else `0`.
  - **Parabolic SAR** `psar_5m/psar_15m/psar_1h` — votes the SAR direction.
  - **ATM option** `atm` — `_series_trend` (EMA-stack + ST-agreement + PSAR) on the ATM CE and the
    **inverted** ATM PE 5m series, combined; abstains unless both legs agree.
- **Two-family extreme guard** — the naked `COMPLETE_BULL/BEAR` buckets now require **both** `ema_1h`
  **and** `st_1h` present-and-agreeing (was `ema_1h` alone).
- **Backtest** (`strangle_loader.py`): warmed ST(10,2)+(10,3)/PSAR spot trackers per TF; memoised
  per-strike ATM EMA/ST/PSAR replay (gated on `w_atm>0`). Knobs in `strangle_config.py`.
- **Live** (`directional_strangle.py` + `strategy/context.py` + `strategy/host.py` +
  `runtime/groups.py`): `IndicatorReader.supertrend_variants`, ST/PSAR reads in `_build_bias_inputs`,
  async ATM read via `atm_suite.atm_trend_read` (gated on `w_atm>0` + a wired `option_bars_col`,
  degrades to abstain), weight-gated ST readiness check.
- **Parity**: both paths use the same tracker classes/params, so identical bars → identical
  `SeriesInputs` → identical `BiasResult` (score_bias is a pure fn of `BiasInputs`).

Backend suite: **1205 passed** (excluding the two documented isolation-flake dirs). Zero new ruff
errors; no new genuine pyright errors.

## Benchmark (120 trading days, recent window, both configs, `--no-mongo`)

`*_multisignal.yaml` = the `*_hedged` baseline + the placeholder new weights
(`w_st_1h=1.5, w_st_15m=1.0, w_st_5m=0.5, w_psar_1h=1.0, w_psar_15m=0.5, w_psar_5m=0.5, w_atm=1.0`).
Baselines kept pristine (new weights `0.0` → identical to shipped behaviour).

| Index | Config | Net | PF | Win | MaxDD | Trades | Halts |
|-------|--------|-----|----|----|-------|--------|-------|
| NIFTY | baseline | +₹13.10L | 11.10 | 80% | ₹23.4k | 1926 | 3 |
| NIFTY | multisignal | +₹13.20L | 10.38 | 78% | ₹27.3k | 2228 | 4 |
| BANKNIFTY | baseline | +₹15.84L | 17.22 | 58% | ₹17.5k | 1403 | 5 |
| BANKNIFTY | multisignal | +₹11.21L | 11.00 | 51% | ₹16.0k | 1650 | 4 |
| SENSEX | baseline | +₹10.46L | 18.44 | 80% | ₹21.5k | 2003 | 1 |
| SENSEX | multisignal | +₹11.35L | 14.54 | 79% | ₹22.8k | 2084 | 3 |

**Verdict on the placeholder weights: do NOT promote.** Net is mixed (NIFTY +0.8%, BANKNIFTY −29%,
SENSEX +8.5%), but **PF drops on all three indices** (the new votes trade more and give up
quality). The live strategy YAMLs stay at `w=0` (inert). Promotion is gated on **walk-forward
tuning** of the new weights (`task backtest:strangle:wf`, stitched-OOS PASS) — a single-window win
is not the bar. This is the expected shape: the plan always specified walk-forward-set weights, not
hand-picked ones.

## Remaining

- **7.4** walk-forward tune the new weights (the real promotion gate).
- **8.2** live smoke on a market day (`dev:trade`): new inputs seed, `bias_evaluated` breakdown shows
  the new votes, backtest↔paper parity holds.
- **8.3** archive — after 7.4 + 8.2.
