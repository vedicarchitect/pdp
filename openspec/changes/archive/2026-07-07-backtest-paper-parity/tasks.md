# Tasks — backtest-paper-parity

> Implementation contract. Every task states the exact file, symbol, and expected behaviour so
> any implementer produces the same result. Line numbers are as-of change authoring and may
> drift — always locate by symbol name. Prerequisite: Change B archived first (strict A→B→C→D).

## 1. Remove VWAP/VWMA as a bias input (shared scoring)

- [x] 1.1 In `pdp/signals/bias.py`, remove the VWAP input and vote entirely:
  drop the `vwap: float | None` field from `BiasInputs` (`:70-71`), the `w_vwap: float = 1.0`
  weight (`:100`), the `_vwap_vote(spot, vwap)` function (`:217-222`), and the
  `(_vwap_vote(...), w.w_vwap, "vwap")` tuple from the vote/ratio table (`:312`). Update the
  module docstring (`:6`) to drop VWAP from the "votes" list.
- [x] 1.2 The `score_bias` normalization divides by the sum of active weights — confirm the
  denominator recomputes correctly with `w_vwap` gone (i.e. VWAP no longer contributes to the
  weight sum). No hardcoded weight-count constant may remain that assumed VWAP was present.
- [x] 1.3 Update `bias.py` unit tests: remove any test that passes `vwap=` into `BiasInputs`
  or asserts a `"vwap"` vote. Add/adjust a test asserting the score is computed from the
  remaining inputs only and that omitting VWAP does not change the bucket boundaries for a
  representative bullish/neutral/bearish input set.

## 2. Remove the live VWAP assembly + futures SID path

- [x] 2.1 In `pdp/strategies/directional_strangle.py`, remove the VWAP assembly: the
  `vwap_sid`/`vwap_s` block (`:629-631`) and the `vwap=vwap_s.vwap if vwap_s else None` arg to
  `BiasInputs(...)` (`:649`). `BiasInputs` no longer accepts `vwap` after task 1.1.
- [x] 2.2 Remove the futures SID path now that nothing consumes it: delete
  `_resolve_front_month_futures_sid` (`:67`), the `self._futures_sid` init block
  (`:150-160`), the `w_vwap=float(p.get("w_vwap", 1.0))` param read (`:205`), and the
  `futures_sid=self._futures_sid` pass-through (`:290`). Remove `futures_security_id` /
  `w_vwap` from the strategy config schema/YAML if declared there.
- [x] 2.3 Grep the module for any remaining `vwap`/`futures_sid` reference and remove dead
  imports/helpers. The strategy must construct `BiasInputs` with no VWAP and resolve no
  futures SID.

## 3. Remove the backtest VWAP computation

- [x] 3.1 In `pdp/backtest/strangle_loader.py`, remove the `_VWAP` running class (`:226-247`)
  and its use in the decision loop: `vwap_run = _VWAP()` (`:179`), `vwap_run.add(...)`
  (`:186`), and `vwap=vwap_run.value()` in the per-bar snapshot (`:203`). The backtest snapshot
  no longer carries a `vwap`.
- [x] 3.2 Confirm `strangle_sim` / `day_loader` pass no `vwap` into `score_bias` after the
  loader change — the shared `BiasInputs` no longer has the field, so a stale kwarg would be a
  hard error. Fix any call site.
- [x] 3.3 Update the loader docstring (`:8`) to drop "tracks per-day VWAP".

## 4. Reconfirm the ₹1.35cr result holds

- [x] 4.1 Re-run the multi-index sweep/backtest for NIFTY, BANKNIFTY, SENSEX over the same
  window used for the ₹1.35cr baseline (NIFTY +₹85.6L, BANKNIFTY +₹35.1L, SENSEX +₹24.7L).
  Record net / PF / MaxDD per index into the backtest warehouse.
- [x] 4.2 Compare the no-VWAP results to the baseline. Because VWAP carried one low vote, the
  expectation is no material regression. Define "material" as any index's net dropping by more
  than ~10% or PF dropping below its prior promotion threshold. If any index regresses
  materially, STOP and surface it to the user before archiving — do not silently proceed.
- [x] 4.3 Note the new figures in the change's completion summary so the roadmap's ₹1.35cr
  claim stays accurate.

## 5. Remove the "futures missing" radar family

- [x] 5.1 In `pdp/backtest/completeness.py`, delete the `futures` family: remove `"futures"`
  from `RADAR_FAMILIES` (`:26`), the `"futures": "futures missing"` label (`:33`), the
  `futures` slot in `FamilyGaps.__slots__` (`:89`), the `futures: set[date]` ctor param and
  assignment (`:98,104`), and the design-note comment (`:24-25`) referencing an unwired
  futures source.
- [x] 5.2 In `pdp/warehouse/coverage.py`, delete `_futures_family` (`:181-185`) and its wiring:
  the `futures_summary, futures_gaps = _futures_family(days)` call (`:263`), the
  `futures=futures_gaps` arg to `FamilyGaps(...)` (`:268`), and the `"futures": futures_summary`
  entry in the coverage response (`:284`).
- [x] 5.3 Grep both modules + `radar_for_date`/`radar_window` for any residual `futures`
  reference and remove it. The radar output for every (index, date) must contain only
  `spot`, `options`, `vix`, `levels_weekly` — no `futures` key.
- [x] 5.4 Update any test in `tests/backtest/` that asserts a `futures` family in the radar
  output.

## 6. Daily backtest-vs-paper convergence check

- [x] 6.1 Build a daily convergence report on the existing
  `GET /api/v1/strangle-backtests/runs/{id}/vs-paper` (`backtest-paper-comparison`). Per index,
  it produces the cumulative backtest−paper divergence to date with attributed `cause` labels
  (now free of the `futures missing` noise), so paper's walk toward the ₹1.35cr/5yr trajectory
  is trackable as paper accumulates.
- [x] 6.2 Surface it as an endpoint (e.g. extend the vs-paper route with a `?cumulative=true`
  mode or a small `/vs-paper/convergence` sub-resource) returning, per index:
  `{index, backtest_cumulative_net, paper_cumulative_net, divergence, top_causes: [...]}`. Do
  not add a new store — compute from the existing per-day alignment rows.
- [x] 6.3 The `cause` attribution must no longer ever emit `"futures missing"` (removed in
  task 5). Verify a day that previously reported only `"futures missing"` now reports `null`
  (genuinely unexplained) or a real cause.

## 7. Verify

- [x] 7.1 `task test` green for `tests/signals/` (bias), `tests/strategies/`, `tests/backtest/`;
  `task lint` clean on all edited modules (pre-existing debt excluded).
- [x] 7.2 Grep the whole `backend/` for `vwap`, `w_vwap`, `_futures_sid`, `futures_security_id`,
  `_futures_family` — no live references remain outside the indicator families
  (`indicators/vwap.py` / `vwma.py`, which stay for chart display only).
- [x] 7.3 `GET /api/v1/coverage` radar output contains no `futures` family for any index.
- [x] 7.4 The re-run sweep figures are recorded and the ₹1.35cr claim is reconfirmed (task 4).
- [x] 7.5 `openspec validate backtest-paper-parity --strict`; archive on green.
