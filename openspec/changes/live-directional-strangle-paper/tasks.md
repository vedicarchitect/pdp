## PROPOSAL — Live DirectionalStrangle Paper Mode Hardening

**Goal:** Make the live paper strategy reliably match the backtest on Monday.
Current state: strategy loads, enters, exits, hedges — but 4 gaps prevent full parity.

---

## 1. Per-signal vote logging (traceability)

- [ ] 1.1 Add a `bias_votes` structlog line on every 5m bar with each of the 9 signal votes and their weighted contributions — mirrors the backtest `status.log` format so you can cross-check live vs replay line-by-line
  - Fields: `score`, `bucket`, `gated`, `v_ema_1h`, `v_ema_15m`, `v_ema_5m`, `v_cam_daily`, `v_cam_weekly`, `v_swing`, `v_vwap`, `v_orb`, `v_pcr`, plus open legs, day P&L
  - `score_bias()` returns votes already — expose them from `BiasResult`

- [ ] 1.2 Add a `leg_status` structlog line showing all open legs (short + hedge) with LTP and MTM (same heartbeat concept as backtest `BarStatus`)

---

## 2. Missing rollup logic

The backtest rolls a leg to a fresh strike when premium decays below 20 (roll to nearest strike with premium ≥ 50). The live strategy has no rollup — it holds stale cheap legs until squareoff.

- [ ] 2.1 In `on_tick` (or `on_bar`), when a short leg's LTP falls below `roll_trigger_prem` (default 20), close the leg and re-open at the next OTM strike with premium ≥ `roll_target_min_prem` (default 50)
  - Close old leg → subscribe new strike → place SELL → update `_short_legs`
  - Close matching hedge → open new hedge at the fresh strike
  - Log `rolled` event with old/new strike + premium

---

## 3. Stop-gate re-entry cooldown

After `pct_stop_half` or `pct_stop_all` fires on a side, the backtest blocks re-entry on that side until the stopped strike's premium stays below the stop-exit level for 3 consecutive 5m bars (≈15 minutes). The live strategy has no such gate — it can re-enter immediately.

- [ ] 3.1 Add `_stop_gate: dict[str, dict]` keyed by opt_type with `{exit_px, sid, n_below}`
- [ ] 3.2 After each stop, record `exit_px` and `sid` for the stopped side
- [ ] 3.3 On every 5m bar, for each gated side: get LTP of stopped sid; if below exit_px increment n_below, else reset; clear gate when n_below ≥ 3
- [ ] 3.4 Gate `_open_short` per side: skip if side in `_stop_gate`; log `stop_gate_wait`
- [ ] 3.5 `_stop_gate.clear()` at squareoff

---

## 4. Weekly Camarilla input

`_build_bias_inputs` always passes `cam_weekly=None`. Weekly Camarilla levels are available from the `pivots` indicator on a weekly timeframe.

- [ ] 4.1 Subscribe NIFTY `1w` bars (or read weekly pivot state from indicator engine)
- [ ] 4.2 Populate `cam_weekly=_to_cam(ind.pivots(self.sid, "1w"))` in `_build_bias_inputs`
- [ ] 4.3 Confirm weekly pivot is warmed on startup from `market_bars`

---

## 5. Live PCR input

`_build_bias_inputs` passes `pcr=None` — the PCR vote is always neutral. In the backtest, PCR is computed per day from OI totals.

- [ ] 5.1 Wire `pcr` from live options chain: read latest CE/PE OI sum from `OptionsChainPoller` or `options/analytics.py` `compute_pcr`
- [ ] 5.2 Refresh PCR every `n` minutes (e.g. each 5m bar) and inject into `BiasInputs`

---

## 6. Indicator timeframe key audit

The live strategy references `"1h"` but the indicator engine may key on `"1H"`. Validate and fix.

- [ ] 6.1 Print all indicator keys on startup (`ind.keys()` or similar) and confirm `"5m"`, `"15m"`, `"1h"` all resolve; fix casing mismatches
- [ ] 6.2 Add smoke-test assertion in `on_init` that at least EMA 5m/15m/1h are warmed

---

## 7. Same-day parity check

- [ ] 7.1 After any trading day, run `backtest/strangle_run.py --from <date> --to <date> --trace` and compare the minute-level `status.log` against the live structlog `bias_evaluated` lines for the same day
- [ ] 7.2 Any mismatch in bucket/score (beyond floating-point tolerance) indicates a parity gap — document and fix
- [ ] 7.3 Add to RUNBOOK §17 as a weekly check

---

## Acceptance criteria
- Monday session: every 5m bar produces a `bias_evaluated` + `leg_status` log line; entries/exits visible in `curl /api/v1/orders`
- Bias score on the same day matches backtest replay within ±0.02
- Rollup fires at least once in a month of paper trading (log `rolled`)
- Stop-gate blocks re-entry on stopped side (log `stop_gate_wait`)
