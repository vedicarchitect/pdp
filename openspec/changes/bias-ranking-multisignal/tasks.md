# Tasks — bias-ranking-multisignal

## 1. New vote inputs in the shared engine (`pdp/signals/bias.py`)
- [x] 1.1 `BiasInputs`: add `st_5m/st_15m/st_1h: tuple[int, int] | None`,
      `psar_5m/psar_15m/psar_1h: int | None`, and `atm_ce_5m/atm_pe_5m: SeriesInputs | None`
      (new `SeriesInputs` bundles each ATM side's EMA/ST/PSAR reads for `_series_trend`). All
      default `None`.
- [x] 1.2 `BiasWeights`: add `w_st_5m/15m/1h`, `w_psar_5m/15m/1h`, `w_atm` — defaulting to `0.0` so
      they are opt-in (inert in score and out of the quorum denominator until a config sets them),
      keeping the shipped 10.5-weight behaviour bit-identical. Configs set starting values;
      walk-forward tunes finals.
- [x] 1.3 `_st_vote(pair)` → `+1` if both variants `+1`, `-1` if both `-1`, else `0`; `None` → abstain.
      `_psar_vote(dir)` → `dir`; `None` → abstain.
- [x] 1.4 Factor the per-series trend read into `_series_trend(SeriesInputs)` and reuse it
      for `atm_ce_5m`/`atm_pe_5m`. `_atm_vote = combine(read_CE, invert(read_PE))` → `+1`/`-1` only
      when both agree, else `0`; abstain if either side absent.
- [x] 1.5 `score_bias`: append the seven new candidates (3 ST + 3 PSAR + 1 ATM) to the vote list so
      they flow through the existing weighted-average, quorum-floor and breakdown machinery unchanged.
- [x] 1.6 `_guard_extreme`: require **both** `ema_1h` and `st_1h` present-and-agreeing for
      `COMPLETE_BULL`/`COMPLETE_BEAR`; else downgrade to `MOST_BULL`/`MOST_BEAR`.
- [x] 1.7 `pdp/signals/CLAUDE.md`: document the three new vote families and the two-family extreme
      guard (replaced the forward-reference note with the real behaviour).

## 2. Startup satisfiability (`pdp/signals/bias.py::check_bias_satisfiability`)
- [x] 2.1 Extend `_TF_FAMILY_REQUIREMENTS` with `w_st_{5m,15m,1h}` → (`{5m,15m,1H}`, `supertrend`) and
      `w_psar_{5m,15m,1h}` → (`{5m,15m,1H}`, `psar`).
- [x] 2.2 Add a `w_atm` branch: require the option-data prerequisite (underlying in
      `options_underlyings`), mirroring the `w_pcr` underlying-poller check.

## 3. Backtest wiring (`pdp/backtest/strangle_loader.py`, `strangle_config.py`)
- [x] 3.1 `_st_psar_series` builds `SuperTrendTracker(fast)` + `SuperTrendTracker(slow)` and
      `ParabolicSARTracker()` per TF (5m/15m/1h); warmed from the same `warmup1` prefix as EMA, then
      replayed per decision bar — mirrors `_ema_series`.
- [x] 3.2 `build_strangle_day` populates `st_*`/`psar_*` on `BiasInputs` via `_at(times, vals, ist)`
      alongside `pcr`/`vix_now`.
- [x] 3.3 ATM: `day_chain` moved above the decision loop; per bar `atm = round(spot/step)*step`,
      `_atm_read_at` resolves CE/PE via `resolve_from_chain` and memoises per-strike EMA/ST/PSAR reads
      (`_option_series_reads`) into `atm_ce_5m`/`atm_pe_5m`. Gated on `weights.w_atm > 0` so it is pure
      overhead-free when the ATM vote is inert; live gates the same read identically.
- [x] 3.4 `strangle_config.py`: added `st_fast_period/mult`, `st_slow_period/mult`, `psar_step`,
      `psar_max_step`, `atm_trend_enabled` knobs (defaults match live MATRIX_ST_VARIANTS + PSAR
      defaults) + validation; `from_dict`/`to_dict` handle them via `asdict` (all primitives).

## 4. Live wiring (`pdp/strategies/directional_strangle.py`, `strategy/context.py`)
- [x] 4.1 `IndicatorReader.supertrend_variants(sid, tf)` accessor over
      `IndicatorEngine.get_supertrend_variants`. The live watchlists already configure a suite on
      5m/15m/1H (ema+supertrend+psar+pivots+period_levels), so the variant trackers populate.
- [x] 4.2 `_build_bias_inputs` reads `(dir_10_2, dir_10_3)` (`_st_pair_from_variants`) + PSAR direction
      per TF, and the ATM CE/PE 5m trend via `atm_suite.atm_trend_read` (async `_atm_trend_reads`, run
      in `on_bar` off the bias fn, gated on `w_atm>0` + a wired `option_bars_col`, degrades to abstain).
      `weights_from_params` reads the new weights (default 0.0). `option_bars_col` wired through
      `StrategyContext`/`StrategyHost.set_option_bars_col`/`groups.py`.
- [x] 4.3 `check_readiness` "Indicators" already gates PSAR (a suite family in `seeding_summary`); added
      an explicit **weight-gated** ST-variant check (the matrix variants aren't in `seeding_summary`), so
      an unseeded *weighted* `st_*` blocks entry like an unseeded EMA, while a zero-weight `st_*` stays
      out of the gate (parity with `strangle-readiness-indicators-truthful`).

## 5. Config + watchlists
- [x] 5.1 The live watchlists already carry `supertrend`+`psar` on 5m/15m/30m/1H, so no watchlist
      change was needed. New backtest **benchmark variant** configs
      `backtest/configs/strangle_{nifty,banknifty,sensex}_multisignal.yaml` carry the ST/PSAR/ATM knobs
      + non-zero new weights; the three `*_hedged.yaml` baselines are left pristine (new weights default
      0.0 → inert) so the A/B compares new-vs-current cleanly and walk-forward tunes the variant.

## 6. Tests (`backend/tests/`)
- [x] 6.1 `tests/signals/test_bias.py`: `_st_vote` agreement table; `_psar_vote`; `_series_trend`;
      `_atm_vote` (PE inversion; CE-up+PE-down ⇒ bullish; conflict ⇒ 0); abstention when any new
      input is `None`; extreme guard now needs both `ema_1h` and `st_1h`. Also updated the
      backtest `test_strangle_sim.py` bull/bear fixtures with agreeing `st_1h`.
- [x] 6.2 `tests/backtest/test_strangle_loader.py`: `test_loader_populates_supertrend_and_psar_votes`
      (st_*/psar_* warmed + set); `test_loader_atm_read_off_by_default_on_by_weight` (ATM inert at
      w_atm=0, resolves at the ATM strike when weighted).
- [x] 6.3 Parity: `test_option_series_reads_parity_with_live_tracker_sequence` — the loader's ATM option
      read matches an independent replay through the exact tracker classes/params `atm_suite.atm_trend_read`
      uses, so identical option bars produce an identical `SeriesInputs` on both paths (score_bias is a
      pure fn of `BiasInputs`, so field-equal inputs ⇒ equal `BiasResult`).
- [x] 6.4 Full backend suite green: **1205 passed** (`tests/ --ignore=observability --ignore=jobs`,
      the two documented isolation-flake dirs). Zero new ruff errors; new-code pyright shows only the
      pre-existing motor/dict Unknown noise, no genuine type errors.

## 7. Benchmark evaluation (the user's ask)
- [x] 7.1 A/B run harness verified: the `*_multisignal.yaml` variant and the `*_hedged.yaml` baseline
      both run cleanly through `backtest/strangle_run.py` (warmup prefix intact, new votes firing).
- [~] 7.2 **120-trading-day A/B run per index (recent window, both configs).** Full 5-year run deferred
      (multi-hour compute) — the 120-day A/B is already conclusive for the go/no-go on these weights:

      | Index | Baseline (`_hedged`) Net / PF / Win / MaxDD | Multisignal (`_multisignal`) Net / PF / Win / MaxDD | Δ Net |
      |-------|----------------------------------------------|------------------------------------------------------|-------|
      | NIFTY | +₹13.10L / 11.10 / 80% / ₹23.4k | +₹13.20L / 10.38 / 78% / ₹27.3k | +0.8% (worse PF/Win/DD) |
      | BANKNIFTY | +₹15.84L / 17.22 / 58% / ₹17.5k | +₹11.21L / 11.00 / 51% / ₹16.0k | **−29%** |
      | SENSEX | +₹10.46L / 18.44 / 80% / ₹21.5k | +₹11.35L / 14.54 / 79% / ₹22.8k | +8.5% (worse PF) |

      PF drops on all three indices → placeholder weights not promotable (full table in README).

- [ ] 7.3 Warehouse `POST /compare` + `--mongo` persistence not run (the CLI A/B above is the same
      metric comparison without needing the API up); revisit if the tuned weights warrant a stored run.
- [ ] 7.4 **Walk-forward tune the new weights — REQUIRED, NOT DONE.** The hand-picked placeholder
      weights (`w_st_1h=1.5, w_st_15m=1.0, w_st_5m=0.5, w_psar_*=1.0/0.5/0.5, w_atm=1.0`) do **not**
      clear the bar: flat-to-slightly-worse on NIFTY, materially worse on BANKNIFTY. **Do not promote
      these weights to the live `strategies/directional_strangle_*.yaml` (still at w=0, inert).** Run
      `task backtest:strangle:wf` (stitched-OOS) to search the new weights before any promotion.
      **2026-07-26: a prior session had already promoted these placeholder weights into the three
      live YAMLs (uncommitted); found during `/pdp-session-wrap` and reverted back to `w=0.0` per
      explicit user decision after re-confirming the -29% BANKNIFTY regression — see
      `memory/bias_ranking_multisignal.md`.**

## 8. Verify + archive
- [x] 8.1 `openspec validate --strict bias-ranking-multisignal` → valid.
- [ ] 8.2 Live smoke: a `dev:trade` session confirms the new inputs seed (readiness clears), the
      `bias_evaluated` breakdown shows the new votes present, and backtest↔paper parity holds.
      **Gated on a market-day session (code-complete).**
- [ ] 8.3 `openspec archive bias-ranking-multisignal` — **blocked on 7.4 (walk-forward tune) + 8.2
      (live smoke)**. The engine/backtest/live wiring + tests are done and green; promotion of the new
      weights is deliberately withheld pending walk-forward. **Pending user go-ahead.**
