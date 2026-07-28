# Tasks — eod-walkthrough-report

## 0. Correctness first (blocks everything else)
- [x] 0.1 `close_partial_leg` (`pdp/backtest/strangle_sim.py`): snapshot `avg_entry` before mutating
      `total_qty`; rewrite `total_cost` from the snapshot, not the post-mutation value.
- [x] 0.2 Add the day-loss-cap check to `close_partial_leg`, mirroring `close_leg`.
- [x] 0.3 Add a `half_stopped` one-shot latch to the backtest leg (set on partial-stop, cleared on
      `open_leg`/`close_leg`), mirroring live's `OpenLeg.half_stopped`.
- [x] 0.4 `BiasWeights.vix_gate_enabled: bool = False` (`pdp/signals/bias.py`); `_vix_gate` returns
      `(False, "vix_gate_disabled")` as its first check when the flag is off.
- [x] 0.5 Remove the independent VIX workarounds: `strangle_run.py`'s skip-load branch,
      `directional_strangle.py`'s four `if self._vix_gate_enabled else None` null-outs (VIX stays
      loaded for reporting; it just no longer gates by itself).
- [x] 0.6 Move `vix_gate_enabled` out of `StrangleConfig` top level into its nested `weights:` block;
      add a one-release compat shim in `from_dict` that migrates a legacy top-level key with a
      deprecation warning.
- [x] 0.7 Fix `weights_from_params` (`directional_strangle.py`) to map every `BiasWeights` field
      generically from its dataclass defaults, instead of a hardcoded `w_*`/`th_*` subset that
      silently dropped `vix_spike_pct`, `vix_day_high_eps`, `pcr_bull`, `pcr_bear`,
      `min_quorum_weight_frac`.
- [x] 0.8 Regression tests: `tests/backtest/test_strangle_partial_close.py` (avg-entry preserved,
      day-loss cap trips from a partial close, half-stop latch); `tests/signals/test_bias.py`
      extended for `vix_gate_enabled=False` producing an identical `BiasResult` with or without VIX
      inputs.

## 1. Widen the traces
- [x] 1.1 `BarStatus` (`strangle_sim.py`) gains `bias_inputs`, `bias_result`, `pe_lots`, `ce_lots`,
      `leg_buckets`, `cooloff`, `half_stopped`, `unrealized`, `done`, `done_reason` — all optional,
      defaulted, no change to `format_status_line` or the warehouse `build_decision_docs` path.
- [x] 1.2 `StrangleDayData` gains `spot_1m: list[Bar]` so the report can render a true per-minute
      ribbon without changing the engine's 5-minute decision cadence.
- [x] 1.3 `BiasResult` gains `bucket_raw`, `quorum_forced_neutral`, `extreme_guard_applied`,
      `gate_reason`; `score_bias` refactored to compute and return them.
- [x] 1.4 `IntradayBarStatus` (`intraday_sim.py`) widened with the per-side condition map
      `evaluate_entry` already builds (`_conds`, previously discarded), `EntryBlock` reason, the
      winning `ExitSignal.detail`, EMA9/EMA20, `st_15m_dir`, Camarilla levels, hedge leg,
      `rolls_today`, cool-off remaining, unrealized MTM.
- [x] 1.5 Both loaders (`strangle_loader.py`, `intraday_loader.py`) populate the new fields.

## 2. Renderer + findings engine
- [x] 2.1 `pdp/backtest/walkthrough.py` (new): `MinuteRow`, `StrategySection`, `MarketContext`
      (incl. `day_type`), `Provenance`, `LiveOverlay`, `render_day()`, `index_row()`. Pure function,
      plain pipe tables, no new dependencies.
- [x] 2.2 `pdp/backtest/walkthrough_checks.py` (new): `Finding` dataclass + detector set —
      `F-AVG-DRIFT`, `F-COST-QTY`, `F-PNL-RECON`, `F-HALT-BREACH`, `F-TP-MATH`, `F-STOP-RESET`,
      `F-STRADDLE`, `F-ROLL-INWARD`, `F-PRICE-SRC`, `F-STALE-BAR`, `F-QUORUM`, `F-VIX-ACTIVE`,
      `F-FLAT-MOVE`, `F-NO-HEDGE`, `F-DATA-GAP`.
- [x] 2.3 `_opens_risk()` helper distinguishes a fill that opens/grows risk from one that closes a
      protective hedge, so `F-HALT-BREACH` does not misfire on hedge-close SELLs.
- [x] 2.4 Tests: `tests/backtest/test_walkthrough.py` (renderer, synthetic days), 
      `tests/backtest/test_walkthrough_checks.py` (each detector: one positive + one negative
      fixture).

## 3. Runner, task, skill
- [x] 3.1 `backend/backtest/walkthrough_run.py` (new): replays both engines over a requested window
      via `simulate_strangle_day`/`simulate_intraday_day`, writes one markdown file per day plus
      `INDEX.md`. Flags: `--date`, `--from/--to`, `--days/--start`, `--underlying`,
      `--strangle-config`, `--intraday-config`, `--out-dir`, `--vix-sid`, `--no-index`, `--force`.
- [x] 3.2 Date selection defaults to today (IST) only when no selector is passed; every other
      selector (single date, range, trailing days) resolves an arbitrary historical window through
      the identical path.
- [x] 3.3 Non-trading-day exit (no file written); `cadence_gap_days` banner + `F-DATA-GAP`; NIFTY
      763-day blackout refuses without `--force`; config resolved as-of the requested date via
      `lot_size_for_date()`.
- [x] 3.4 `Taskfile.yml`: `eod:walkthrough` task.
- [x] 3.5 `.claude/skills/eod-walkthrough/SKILL.md` (new): pdp shape-A skill, `/eod:walkthrough
      [date|range]`, runs the task, reads FINDINGS, summarizes top findings, appends to `INDEX.md`.

## 4. Verification
- [x] 4.1 `task test`: 1444 passed (observability's 3 known asyncio-teardown-race flakes reproduced
      standalone-green both before and after this change — pre-existing, not introduced).
- [x] 4.2 `ruff check` clean on every new/modified file in this change.
- [x] 4.3 Numerically prove the partial-close fix: 5→3 lot reduction at avg 100 stays 100 (was 166.67
      under the old ordering).
- [x] 4.4 Numerically prove the VIX unification: regenerate 2026-07-21 → 2026-07-24 and confirm every
      bar reads `vix_gate_disabled`; 2026-07-22 trades (+6,889) rather than the old doc's claimed
      zero fills.
- [x] 4.5 `backend/backtest/manual/2026-07-21.md` .. `2026-07-24.md` + `INDEX.md` generated; every
      fill row shows underlying spot; 07-22's why-no-trade census names the real blocking reason.
- [x] 4.6 Determinism test: `tests/backtest/test_walkthrough.py::test_render_is_deterministic` at
      the renderer level, plus an end-to-end re-run of 2026-07-24 confirming the only diff between
      two generations is the `generated_at` timestamp.
- [x] 4.7 `openspec validate --strict eod-walkthrough-report`.

## 5. Docs
- [x] 5.1 `backend/pdp/backtest/CLAUDE.md`: add `walkthrough.py`, `walkthrough_checks.py` to the
      Active files table.
- [x] 5.2 `backend/backtest/CLAUDE.md` (repo-root non-pdp dir table): add `walkthrough_run.py` +
      `manual/` folder purpose.
- [x] 5.3 Root `CLAUDE.md` milestone entry for this change.

## 6. Follow-ups (explicitly not bundled here)
- [ ] 6.1 Restore `leg_buckets` after a roll (`_roll_leg` never restores what `close_leg` pops).
- [ ] 6.2 Backtest/live take-profit formula parity.
- [ ] 6.3 Square-off price source: `db.open` → close.
- [ ] 6.4 Neutral-bucket straddle / roll-target / opposite-side-cooloff policy decision.
- [ ] 6.5 Re-baseline the promoted NIFTY/BANKNIFTY/SENSEX runs against the partial-close fix.
- [ ] 6.6 `openspec archive eod-walkthrough-report` (after 4.6/4.7 and docs land).
