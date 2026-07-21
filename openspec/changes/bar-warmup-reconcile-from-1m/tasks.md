# Tasks — bar-warmup-reconcile-from-1m

## 0. Diagnostics (read-only, done this session)
- [x] 0.1 Confirmed via live diagnosis (2026-07-19): NIFTY 1m market_bars pristine (926k docs,
      full 375-bar sessions through Jul 17); 5m/15m/30m/1H corrupt — Jul 14 15m had 50 bars (dupes)
      vs 25, Jul 17 15m had 0 bars (gap).
- [x] 0.2 Confirmed `indicator-warmup-derive-from-1m` is already on this branch
      (`_derive_bars_from_1m`, `_replace_derived_bars`, `_DERIVABLE_TF_MINUTES` all present in
      `warmup.py`), but its call site (`warmup.py:270`) is gated on `len(bars) < target_bars` —
      a depth-shortfall check that misses the duplicate case (count already ≥ target).
- [x] 0.3 Manually repaired via `scripts/oneoff/rebuild_market_bars.py` for NIFTY/BANKNIFTY/SENSEX
      (2026-06-01→2026-07-17, 5m/15m/30m/1H) — confirmed clean, user confirmed values match Kite.
      This change makes that repair automatic on every future boot instead of a manual one-off.

## 1. Reconciliation helper
- [x] 1.1 `_bars_disagree(stored: list[BarClosed], derived: list[BarClosed]) -> tuple[bool, dict]` —
      index both by `bar_time`; disagreement if: stored has a `bar_time` not in derived's boundary
      set (orphan/duplicate), derived has a boundary stored is missing (gap), or OHLCV differs at a
      shared boundary (misalignment). Returns a reason dict (`{"duplicates": n, "gaps": n,
      "mismatched": n}`) for logging.
- [x] 1.2 Reuse existing `_derive_bars_from_1m` + the same `bar_is_complete` filter already used at
      `warmup.py:274-278` — no new rollup logic, only a new comparison step.

## 2. Wire into `_warm_one`
- [x] 2.1 For `timeframe in _DERIVABLE_TF_MINUTES`, fetch 1m and derive **unconditionally**
      (independent of the `len(bars) < target_bars` branch), then call `_bars_disagree`.
- [x] 2.2 On disagreement: `_replace_derived_bars` (existing function, reused as-is) and log
      `indicator_warmup_reconciled_from_1m` with the discrepancy counts + security_id/timeframe.
- [x] 2.3 On agreement: no write, `bars` stays as fetched from Mongo (avoid needless
      delete_many/insert on a healthy store — keep boot cheap and idempotent).
- [x] 2.4 Keep the existing depth-shortfall branch for the case 1m itself doesn't cover the full
      required window (falls through to the Dhan chunked fetch, unchanged).

## 3. Tests
- [x] 3.1 `test_bars_disagree_detects_duplicate_boundary` — stored has 2 bars at one 15m boundary,
      derived has 1 → disagreement, duplicates=1.
- [x] 3.2 `test_bars_disagree_detects_gap` — derived has a boundary stored lacks → disagreement,
      gaps=1.
- [x] 3.3 `test_bars_disagree_detects_mismatched_ohlcv` — same boundary, different close → mismatch.
- [x] 3.4 `test_bars_disagree_false_on_healthy_store` — stored == derived → no write.
- [x] 3.5 `test_warm_one_reconciles_duplicate_store_even_when_depth_met` — regression test for the
      exact Jul 14 scenario (stored count ≥ target_bars but duplicated) — asserts
      `_replace_derived_bars` is called and the tracker seeds from the reconciled bars, not the
      duplicated ones.
- [x] 3.6 `test_warm_one_skips_rewrite_on_healthy_store` — stored already matches derived → assert
      no `delete_many`/`_persist_bars` call (idempotency/perf guard).
- [x] 3.7 Existing warmup suite still green: 46 passed (40 baseline + 6 new).
- [x] 3.8 `task test` full green: 1209 passed (baseline 1203 + 6 new), 0 failed. Ruff net-zero new
      findings vs HEAD (verified via `git stash` diff — identical 8 pre-existing findings, same
      lines shifted).

## 4. Verify + archive
- [x] 4.1 `openspec validate --strict bar-warmup-reconcile-from-1m` — valid.
- [x] 4.2 Boot smoke via new `backend/scripts/warmup_premarket.py` (Workstream B) against the live
      dev DB (2026-07-19): **found and repaired real 1H corruption** on all 3 indices — NIFTY
      stored=1921 vs derived=976 (945 duplicates), BANKNIFTY stored=1911 vs derived=965 (938
      duplicates), SENSEX stored=1920 vs derived=975 (945 duplicates) — `indicator_warmup_reconciled_from_1m`
      logged for each; final `indicator_seeding_summary` shows `unseeded_count=0` for all three
      `directional_strangle_*` configs.
- [x] 4.3 Restart-pattern coverage: the reconciliation runs unconditionally on every
      `warm_up_indicator_engine` call, i.e. every engine boot and every `task warmup`/`dev:trade`
      invocation — a restart after minutes, hours, or days all take the same code path, no
      restart-age-specific logic needed. `dev:trade` now runs `warmup_premarket.py
      --allow-market-hours` as a prerequisite step (Taskfile.yml) so this is automatic, not a
      manual step to remember.
- [ ] 4.4 `openspec archive bar-warmup-reconcile-from-1m` — hold until the next live/market-hours
      session confirms the engine's own boot warmup (not just the standalone script) exercises this
      path cleanly end-to-end (same code, but confirm in the actual trading process).
