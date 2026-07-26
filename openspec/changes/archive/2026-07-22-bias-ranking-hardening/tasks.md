# Tasks — bias-ranking-hardening

## 1. Backtest warmup prefix (root-cause of the false loss)
- [x] 1.1 `day_loader.load_window`: add `warmup_days: list[date] | None = None` — widen only the
      **spot** query range to cover the warmup prefix; keep expiry/chain/completeness/`valid_days`
      keyed to `days` so warmup days load as spot but are never traded.
- [x] 1.2 Shared helper `day_loader.warmup_prefix(days, n=WARMUP_BIZ_DAYS)` (≈30 business days →
      ≥20 trading days) returns the spot-only runway immediately before `days[0]`. `strangle_run.py`
      passes `warmup_days=warmup_prefix(chunk)` per quarter-chunk to `load_window`.
- [x] 1.3 Wire the same helper into every other bias-path backtest entry point so none starves at a
      chunk/fold boundary: `sweep_engine.py` (per quarter-chunk, leaderboard) and
      `strangle_walkforward.py` (per fold, promotion gate). `replay.py` already prepends its own
      warmup; `sweep_all.py` is the SuperTrend index sim, not the bias path.
- [x] 1.4 Confirm `_prior_days_1m`/`_prior_session_1m`/`_prior_week_1m` now resolve for the first
      traded day of a short window (they read `window.spot_1m_by_day`, now populated). Covered by
      `test_day_loader_warmup.py` (incl. `warmup_prefix` unit tests) + `test_strangle_loader.py`.

## 2. Ranking guards in the shared engine (`pdp/signals/bias.py`)
- [x] 2.1 `BiasWeights`: add `min_quorum_weight_frac: float` (default `0.25` — ORB+PCR-only 0.19
      fails, ema_1h+pcr 0.286 passes).
- [x] 2.2 `score_bias`: compute `present_frac = weight_total / total_configured_weight`
      (denominator = Σ non-zero `w_*`); if below `min_quorum_weight_frac`, force `NEUTRAL`.
- [x] 2.3 `BiasResult`: add `present_weight_frac` field; populate on every evaluation. Include it in
      the `reason` string (`quorum=…`).
- [x] 2.4 Extreme-bucket guard (`_guard_extreme`): for `COMPLETE_BULL`/`COMPLETE_BEAR`, requires
      `ema_1h` present and agreeing; else downgrade to `MOST_BULL`/`MOST_BEAR`. Applied after
      `_bucket_for`.
- [x] 2.5 `pdp/signals/CLAUDE.md`: document quorum floor + extreme-bucket guard semantics.

## 3. Tests (`backend/tests/`)
- [x] 3.1 `tests/signals/test_bias.py`: ORB+PCR-only inputs → `NEUTRAL` (quorum floor); quorum math +
      `present_weight_frac` reported.
- [x] 3.2 `tests/signals/test_bias.py`: `COMPLETE_BEAR` downgraded to `MOST_BEAR` when `ema_1h`
      abstains/disagrees; retained when `ema_1h` present and agrees (both bull and bear).
- [x] 3.3 `tests/backtest/test_day_loader_warmup.py`: warmup days load spot but aren't traded;
      `test_strangle_loader.py` covers warmed higher-TF EMAs.
- [x] 3.4 Existing bias/parity tests still green (signals/strategy/strategies/backtest: 446 passed —
      +2 for the `warmup_prefix` helper unit tests).

## 4. Regression evidence
- [x] 4.1 Single-day NIFTY 2026-07-21 backtest (`--from 2026-07-21 --to 2026-07-21`): warmed vote set
      (`ema_1h`/`ema_15m`/`cam_daily` present, not abstaining), defended positions (never naked),
      **Net +₹22,971 (gross +24,232), 0 halts, Win 100%** — replaces the false −₹21,572 halted.
- [x] 4.2 Healthy multi-week window unaffected: `--from 2026-06-23 --to 2026-07-21` →
      **Net +₹1,67,499, PF 36.30, Win 93%, MaxDD ₹4,745, 0 halts** (2026-07-21 identical to the
      standalone run — warmup is consistent whether a day runs alone or in-window).
- [x] 4.3 Full backend suite: **1227 passed**, 3 failed — the 3 failures are the documented
      pre-existing `tests/observability/test_processor.py` isolation flakes (pass in isolation: 7
      passed), not caused by this change.

## 5. Verify + archive
- [x] 5.1 `openspec validate --strict bias-ranking-hardening` — valid.
- [ ] 5.2 `openspec archive bias-ranking-hardening` (after task test green + regression evidence).
      **Pending user go-ahead to archive + commit.**
