# bias-ranking-hardening

## Why

On 2026-07-21 a single-day NIFTY directional-strangle backtest reported `−₹21,572, halted`. It was
an **artifact, not a real loss**, and it exposed two compounding gaps in the shared bias engine
(`pdp/signals/bias.py::score_bias`), which drives **both** backtest and live:

1. **Backtest warmup starvation.** `strangle_loader.build_strangle_day` warms EMAs from
   `_prior_days_1m(window, trade_date, 20)`, which reads only the days already loaded into the
   in-memory `WindowData`. `strangle_run.py` loads only the *trade days requested*, so a short window
   (and the first ~8 trading days of every quarter-chunk in a long run) has no prior days in the
   window to warm from — even though the spot bars exist in Mongo the whole time. All higher-TF EMAs
   then abstain.
2. **Abstention-saturation.** `score_bias` computes `Σ(w·vote)/Σ(w)` over **present inputs only**.
   With 6 of 8 votes abstaining, the score renormalizes onto ORB+PCR (2.0 of 10.5 total weight) and
   trivially reaches `|score| ≥ 0.75` → `COMPLETE_BEAR` → naked `0 PE : 5 CE`. The two extreme
   buckets (`COMPLETE_BULL` 5:0, `COMPLETE_BEAR` 0:5) are the only undefended positions in the ratio
   table and the easiest to reach when starved.

Proof: the same day in a 5-week warm window scored **+0.091 (neutral)** → balanced 6:6 →
**+₹24,232**; the 18-day window netted **+₹1,81,800, PF 12.76, Win 89%**.

Live is already gated (`directional_strangle.check_readiness` blocks entry on any unseeded indicator),
so the naked bet cannot fire live — but the backtest path has no equivalent gate, and the ranking
itself has no floor against saturating off a thin vote set. This change fixes both: the data source
(backtest warmup) and the ranking (a quorum floor + a guard on the naked buckets) so the engine can
never again turn insufficient data into a saturated directional bet.

## What Changes

- **Backtest warmup prefix.** `load_window` accepts spot-only `warmup_days`; a shared
  `day_loader.warmup_prefix()` helper (`WARMUP_BIZ_DAYS = 30`) computes the ~20+ prior-trading-day
  spot runway loaded before each quarter-chunk's first traded day (excluded from results/P&L). Every
  bias-path backtest entry point uses it in lockstep — `strangle_run.py` (single run), `sweep_engine.py`
  (leaderboard), and `strangle_walkforward.py` (promotion gate) — so none decides on a starved vote
  set at a chunk/fold boundary. The reported trade window is unchanged; only the loaded window widens.
  No "refuse short window" branch — the data always exists, so we always pad.
- **Quorum floor.** `BiasWeights.min_quorum_weight_frac`; if the fraction of *configured* weight
  actually present is below it, `score_bias` forces `NEUTRAL` regardless of score. The present
  fraction is surfaced on `BiasResult` for observability.
- **Extreme-bucket guard.** `COMPLETE_BULL/BEAR` are unreachable unless the higher-TF trend vote
  (`ema_1h`) is present and agrees with the bucket's direction; otherwise the bucket downgrades to the
  nearest defended bucket (`MOST_BULL/BEAR`, which keep a protective opposite side).

## Impact

- Affected specs: `bias-input-completeness` (ADD quorum-floor, extreme-bucket-guard, and
  backtest-warmup requirements).
- Affected code: `backend/pdp/signals/bias.py` (`score_bias`, `BiasWeights`, `BiasResult`),
  `backend/pdp/backtest/day_loader.py` (`load_window` warmup param + shared `warmup_prefix`/
  `WARMUP_BIZ_DAYS` helper), and the warmup wiring across all three bias-path entry points —
  `backend/backtest/strangle_run.py` (per chunk), `backend/pdp/backtest/sweep_engine.py` (per chunk),
  and `backend/backtest/strangle_walkforward.py` (per fold). No schema/migration changes.
- This change is the safety base for the follow-up `bias-ranking-multisignal` (adds SuperTrend / SAR
  / ATM votes); the extreme-bucket guard there extends to also require `st_1h` agreement.
