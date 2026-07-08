---
name: backtest:promote
description: Review a walk-forward run's PASS/REVIEW rationale (stitched-OOS metrics, per-threshold breakdown, fold win-rate), then promote a PASS run to a paper strategy. Refuses non-PASS runs. Use when the user wants to move a validated backtest to paper trading.
metadata:
  author: pdp
  version: "1.0"
---

Review promotion evidence and, if warranted, promote a run to paper.

## Input

A `run_id` (walk-forward run) after `/backtest:promote`. Optionally an operator note to attach.

## Steps

1. **Fetch the run** and check its verdict:

   ```
   curl -s http://localhost:8000/api/v1/strangle-backtests/runs/<run_id>
   ```

   If `verdict` is not `PASS`, **stop and refuse** — show the `stitched_oos` metrics and explain
   which threshold(s) failed (net>0, PF>1.2, Sharpe>0.5, ≥60% positive OOS folds — the single
   source of truth is `pdp/backtest/store.py:verdict_breakdown`). Do not promote a REVIEW run.

2. **If already promoted** (`promotion_state == "promoted"`), fetch and show the existing
   rationale instead of re-promoting:

   ```
   curl -s http://localhost:8000/api/v1/strangle-backtests/runs/<run_id>/promotion
   ```

3. **For a fresh PASS run**, show the evidence to the user before acting: stitched-OOS net/PF/
   Sharpe, the per-threshold PASS-vs-actual breakdown, and positive-fold fraction. This is an
   audit action (writes a paper-strategy YAML) — confirm with the user before calling promote
   unless they've already explicitly asked to promote this exact run_id.

4. **Promote**:

   ```
   curl -s -X POST http://localhost:8000/api/v1/strangle-backtests/runs/<run_id>/promote \
     -H "Content-Type: application/json" -d '{"note": "<optional operator note>"}'
   ```

   Returns `{strategy_id, yaml_path, run_id, verdict, promoted_at}`. The written
   `strategies/<strategy_id>.yaml` is paper-first (no `LIVE` flag) — do not add one yourself.

5. **Confirm**: report the new `strategy_id` and `yaml_path`, and that it will be picked up by
   `StrategyHost` on next restart (`task dev`) in paper mode. Remind the user that flipping to
   LIVE is a separate, manual, deliberate step per non-negotiable #2.
