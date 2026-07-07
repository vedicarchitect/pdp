---
name: strangle:review
description: Analyze today's directional strangle activity log and produce a structured trade-session review with decisions, P&L, anomalies, backtest-vs-paper divergence, and suggestions. Use when the user wants to review the live strangle session after market hours or during the day.
metadata:
  author: pdp
  version: "2.0"
---

Analyze the directional strangle trading session and produce a structured review.

## Input

Optionally specify a date after `/strangle:review` (e.g., `/strangle:review 2026-06-28`).
If omitted, use today's IST date.

## Steps

1. **Locate the session data — per underlying (NIFTY/BANKNIFTY/SENSEX run as separate
   strategies since the multi-index migration)**

   Two sources exist; prefer OpenSearch when available, JSONL is always the fallback and
   source of truth (OpenSearch is a derived/queryable copy, not a replacement — JSONL files
   are written directly by the live strategy code regardless of OpenSearch state):

   - **Preferred — OpenSearch** (only has data if `OPENSEARCH_ENABLED=1` was set during the
     session): `GET /api/v1/analysis/session?date=<YYYY-MM-DD>&strategy_id=directional_strangle_<underlying>`
     (lowercase underlying: `directional_strangle_nifty`, `_banknifty`, `_sensex`) for each
     of the three. Returns 404 if no events indexed for that day/strategy — treat as "not
     available, fall back to JSONL" rather than an error. Response shape:
     `{date, strategy_id, summary: {total_bias_events, total_leg_opens, total_leg_closes,
     total_stops, total_tps, total_rolls, day_realized_pnl, buckets_seen}, bars: [{bar_time,
     bucket, score, spot, bias_votes, leg_status, actions}]}`.
   - **Fallback / always-available — raw JSONL**: `backend/logs/directional_strangle_<underlying>/<YYYY-MM-DD>.log`
     (one file per underlying — NOT a single `directional_strangle/<date>.log`, that path
     doesn't exist post multi-index migration). Each line is a JSON object; lines with an
     `"event"` key (no `event_type`) are `run_start`/config dumps — skip those. Lines with
     `event_type` are the actual session events.

   Read all three underlyings' data. If a given underlying's file/index has no events for
   the date, say so for that underlying specifically and continue with the other two.

2. **Parse events by type**

   Group lines by `event_type`. Expected types:
   - `bias_evaluated` — score, bucket, votes per signal
   - `leg_status` — open legs with LTP/MTM at each ~5m bar
   - `leg_open` — entry: side, strike, lots, entry_price, is_hedge
   - `leg_close` — exit: reason (`square_off`/`bucket_change`/`premium_stop`/`take_profit`/
     `roll`/`day_loss_cap`), no direct `pnl` field — compute from paired entry/exit `leg_status.mtm`
   - `stop_half` / `stop_all` — premium stop: entry, ltp, remaining lots
   - `rolled` — rollup attempt: old_strike, new_strike, old_ltp, new_ltp, `result` (may be
     `skipped_low_prem` — a declined roll, not a completed one)
   - `stop_gate_wait` — blocked re-entry: opt_type, exit_px, ltp, n_below
   - `bucket_change` — regime shift: old_bucket → new_bucket
   - `day_loss_cap` — day halt, second emission carries `day_pnl`
   - `square_off` — EOD close

   Note: `leg_close` at a `bucket_change` boundary is usually paired with an immediate
   `leg_open` at the same/adjacent tick (position resize, not a realized round-trip) —
   don't treat these as trades with meaningful holding time. Also watch for **backend
   restarts mid-session**: multiple `run_start` lines followed by a position closing and
   reopening at a fresh entry price with ~0 realized P&L is a state resync after a
   restart, not a real trade — cross-check restart timestamps against known dev activity
   before flagging it as an anomaly.

3. **Produce the session review** — one pass per underlying, then a cross-index section.

   ### Session Summary (per underlying)
   - Date, underlying, mode (paper/live), lot size
   - Opening bucket + score (first `bias_evaluated`)
   - Final bucket + score (last `bias_evaluated`), or halt reason if session stopped early
   - Total bars evaluated (count of `bias_evaluated`)
   - Net day P&L: sum realized closes (`leg_close` with a real exit reason, matched to
     entry via `security_id`) using `(exit_ltp - entry_price) * lots * lot_size` for shorts;
     do not double-count bucket-change resize pairs as P&L events
   - Trade count, leg count by side (PE shorts, CE shorts, hedges)

   ### Bias Timeline
   `HH:MM IST | bucket | score | trigger (bucket_change reason)`

   ### Per-Signal Vote Analysis
   From `bias_evaluated.votes`, average vote per signal. Flag signals consistently
   neutral/absent (e.g. a `pcr` key missing from one underlying's votes all day but present
   in the others — likely a per-underlying data-source gap, not expected behavior).

   ### Trades
   Per underlying: side, strike, entry price, exit price, exit reason, P&L, holding time.

   ### Notable Events
   - `rolled` events (note `skipped_low_prem`/declined rolls separately from completed ones)
   - `stop_gate_wait` streaks (re-entry gate holding, working as designed)
   - **`day_loss_cap`** — always investigate: compare the logged `day_pnl` at halt against
     the configured `day_loss_limit` from that underlying's `run_start.params`. If the
     realized loss at halt materially exceeds the configured limit, that's a lagging-check
     bug worth flagging as high priority (the cap fired reactively after a stop already
     blew past its own `pct_stop_all` threshold, rather than pre-empting it) — check
     `pdp/risk/` for the evaluation cadence.
   - `bucket_change` reversals within the same hour (chop)

   ### Backtest-vs-paper divergence (if a run exists for the date; offer to create one)

   Check whether a backtest run already exists for this date via
   `GET /api/v1/strangle-backtests/runs?strategy_id=<canonical_id>&date=<date>` (or the
   leaderboard/list endpoint — see `pdp/backtest/warehouse_routes.py`). If none exists,
   **ask the user** whether to kick one off now (don't run it silently — it's not free):

   ```
   task backtest:strangle -- --config-file backend/backtest/configs/strangle_nifty_hedged.yaml --from <date> --to <date>
   task backtest:strangle -- --config-file backend/backtest/configs/strangle_banknifty_hedged.yaml --from <date> --to <date>
   task backtest:strangle -- --config-file backend/backtest/configs/strangle_sensex_hedged.yaml --from <date> --to <date>
   ```

   Each run persists to the warehouse (`--mongo` defaults on) and returns a `run_id`. Then
   call `GET /api/v1/strangle-backtests/runs/{run_id}/vs-paper?granularity=day` for a
   day-level `{days: [{date, backtest_net, paper_net, divergence, diverges, cause}]}`
   comparison, or `?granularity=minute&date=<date>` for a minute-aligned view (this mode
   needs OpenSearch session data — falls back poorly if `OPENSEARCH_ENABLED` was off).
   Report `diverges=true` days with their `cause` field verbatim — that's the root-cause
   hint the endpoint already computed (e.g. gap-radar data gaps, VIX-gate mismatch).

   ### Suggestions
   - If PCR was always None/missing for one underlying: note it as a per-underlying wiring gap
   - If cam_weekly/cam_daily flips mid-session aligned with a restart: note as a
     warmup/levels-reload artifact, not necessarily a real signal change
   - If no rollup fired: "Consider reviewing roll_trigger_prem threshold" for that underlying
   - If day halt fired: report the divergence between configured limit and actual loss at
     halt explicitly
   - If backtest-vs-paper diverges: surface the endpoint's `cause` field directly

4. **Offer next action**

   End with: "Run `/strangle:review <date>` for a different date, or `/pdp:health` for
   infrastructure status."
