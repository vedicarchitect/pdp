# Tasks

## 1. Fix

- [x] 1.1 In `DirectionalStrangle._reconcile_divergences`
      (`backend/pdp/strategies/directional_strangle.py`), build a fresh `current: set[str]` of
      currently-diverged security_ids from the memory-vs-broker comparison (both the
      tracked-leg loop and the orphan-broker-position loop), and assign
      `self._divergences = current` at the end of the pass so healed mismatches drop out.
- [x] 1.2 Keep `_flag_divergence` emitting the once-per-shape `LEG_STATE_DIVERGED` alert via
      `self._divergence_shapes` (retained across passes) — split the "record the current sid"
      concern from the "alert once" concern so recomputing `_divergences` does not reset the
      alert rate-limiter. (Signature now takes the target `current` set; the second caller in
      `_close_leg` passes the live `self._divergences` directly.)
- [x] 1.3 Update the `_divergences`/`_divergence_shapes` init comment
      (`directional_strangle.py:~280`) to state that `_divergences` reflects the *current*
      pass and self-clears, while `_divergence_shapes` is the session-long alert de-dup.

## 2. Verify

- [x] 2.1 Unit test (`tests/strategy/test_directional_strangle.py`): three tests added —
      `test_reconcile_divergence_clears_when_mismatch_heals` (flag then heal → `_divergences`
      empties), `test_reconcile_divergence_alert_deduped_across_passes` (persistent mismatch
      alerts exactly once across 3 passes, `_divergence_shapes` retained), and
      `test_reconcile_orphan_broker_position_clears_when_gone`. All pass; 55 passed across the
      strategy/roll-atomicity/crash-recovery files with no regression.
- [x] 2.2 `task test`: 1209 passed (1206 baseline + 3 new reconcile tests), 3 failed — all 3
      the pre-existing `tests/observability/test_processor.py` isolation-flakes (confirmed 7/7
      passing when that file runs alone), unrelated to this change.
- [x] 2.3 `openspec validate --strict strangle-reconcile-latch-clears` — valid.
- [ ] 2.4 Live/paper smoke: with `dev:trade` running and legs open,
      `GET /api/v1/strangle/readiness?strategy_id=directional_strangle_nifty` shows
      `Reconciliation: ok` once any transient post-entry mismatch heals, and NIFTY resumes
      opening new legs on the next qualifying bar.

## 3. Archive

- [ ] 3.1 `openspec archive strangle-reconcile-latch-clears` once 2.4 passes on a live market day.
