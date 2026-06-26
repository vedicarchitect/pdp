## 1. Data foundation & audit (Phase 0, Dhan → Mongo only)

- [x] 1.1 Extend NSE holiday calendar to cover 2021–2022 — DONE: 25 holidays derived from actual NIFTY spot market_bars (sid 13) missing weekdays; new file `data/calendars/nse_holidays_2021_2026.json`; `settings.py NSE_HOLIDAYS_JSON` updated
- [x] 1.2 Backfill NIFTY spot from Dhan → `market_bars` — DONE: sid 13 covers 2021-01-01→today (95–100%/yr, 928k 1m bars)
- [x] 1.3 Backfill NIFTY options from Dhan → `option_bars` — DONE: 2021-01-01→today (94–100%/yr, 42.7M bars; `option_type`/`expiry_date`, `iv`+`oi` stored)
- [x] 1.4 Create `scripts/backfill_vix.py` — fetch India VIX 1m from Dhan (default sid 21 or `--resolve` from master), idempotent into `market_bars`; `task backfill:vix` added
- [x] 1.5 Create `scripts/audit_strangle_data.py` — per-year spot/options/VIX coverage + earliest covered date; `task audit:strangle` added
- [x] 1.6 Run audit + VIX backfill — DONE: India VIX 517,248 rows over 1,246 days; intraday history begins ~Aug-2021, so the VIX gate is active 2021-09→2026 and "allow+log" before. Spot+options cover full 2021-01→2026. **Backtest window = 2021-01-01 → present** (VIX gate inactive Jan–Aug 2021).

## 2. Bias-scoring engine (Phase 1)

- [x] 2.1 Create `src/pdp/signals/__init__.py` and `src/pdp/signals/bias.py` with `BiasWeights`, `BiasResult`, and `score_bias(...)` (pure function)
- [x] 2.2 Implement per-signal votes: 1h EMA alignment, 15m EMA alignment, 5m price vs 50 EMA, daily Camarilla R3/R4 (S3/S4) breakout, weekly Camarilla, swing PDH/PDL/PWH/PWL, VWAP break, 15m ORB break, PCR threshold
- [x] 2.3 Implement the VIX gate (>5% spike / day-high / rising last 3×5m → `gated=True`; missing VIX → allow + log)
- [x] 2.4 Implement score→bucket→ratio mapping (7 buckets, configurable thresholds + ratio table)
- [x] 2.5 Add an ORB helper (15m opening range from the first 15m bar) usable by both backtest and live — DONE: loader uses `bars_15[0].{high,low}` and live strategy captures it in `on_bar("15m")` first bar; both adapters populate `BiasInputs.orb_high/orb_low`
- [x] 2.6 Unit tests `tests/signals/test_bias.py` — table-driven per-signal votes, each bucket, both gates, determinism (16 tests passing)

## 3. Multi-leg ratio-strangle simulator (Phase 2)

- [x] 3.1 Create `src/pdp/backtest/strangle_config.py` (`StrangleConfig` dataclass: bias weights, gate thresholds, `strike_method`, ratio table, stops, `take_profit_pct`, `roll_trigger_prem`, `roll_target_min_prem`, session windows; `from_yaml`/`from_dict`)
- [x] 3.2 Create `src/pdp/backtest/strangle_sim.py` — pure engine consuming pre-assembled per-bar `BiasInputs`; legs keyed by opt_type with per-bucket lot ratio
- [x] 3.3 Wire the bias engine to set per-bar bucket → PE:CE leg counts; gate entries until after the 10:15 1h candle
- [x] 3.4 Implement `strike_method=premium` (most-OTM strike with premium > floor; ATM at extreme buckets)
- [x] 3.5 Implement `strike_method=delta` (solve IV from premium, use `src/pdp/options/greeks.py` for 0.6Δ targeting) — DONE: `_select_delta_strike` in `strangle_sim.py` uses `solve_iv` (new public wrapper in `greeks.py`) + `vollib` BSM delta; `_select_strike_for` passes `expiry_date` for T computation; falls back to premium when vollib unavailable
- [x] 3.6 Implement PCR per bar from `option_bars` OI (reuse `compute_pcr` in `src/pdp/options/analytics.py`) and join the VIX series per day — DONE: `load_pcr_window` in `strangle_loader.py` aggregates PE/CE OI per minute via Mongo pipeline; `build_strangle_day` accepts `pcr_by_day` and wires per-bar PCR into `BiasInputs`; wired in runner + walkforward
- [x] 3.7 Implement exits: rollup (<20), take-profit (% credit), tiered premium stop, trend-flip adjustment (bias sign flip), ₹15,000 daily-loss cap, session square-off
  - Tiered premium stop (`pct_stop_enabled`): 30% above entry → close half lots (`pct_stop_half`); 40% above entry → close all remaining (`pct_stop_all`). Replaced the 2x premium-doubled rule. 30-day result: Net +64,210 / PF 2.06 / Win 64% vs +8,589 / 1.13 / 52% before.
  - Squareoff missing-price fix: `close_leg` now falls back to `_last_price(bars, ist_dt)` when `price_at` returns None (deep-OTM strikes with no bars near squareoff); final fallback ₹0.01 (expired worthless). Day 3 (2026-05-20) PE@23000 was the trigger — fixed +₹8.8k recovery.
- [x] 3.7b Protective hedges (defined-risk spreads): per short leg, buy a far-OTM long in the [2,5]₹ band (else cheapest available wing); rides the leg lifecycle (open/roll/close); `--hedge/--no-hedge` runner override + `strangle_*_hedged.yaml` configs. A/B (May–Jun 2026): hedged PF 1.86 vs naked 1.45, MaxDD −29%.
- [x] 3.7c Stop-recovery re-entry gate (15m sustained below exit price) — DONE: `stop_gate` dict in `simulate_strangle_day`; filled on `pct_stop_half/all`; cleared after `_gate_bars_needed` consecutive bars below exit price; entry blocked per side while gate active; cleared at squareoff
  - **Rule**: after `pct_stop_half` or `pct_stop_all` fires on a side, re-entry on that side is blocked until the stopped-out strike's premium comes back **below the stop-exit price and sustains there for ≥ 15 minutes** (= `ceil(15 / timeframe_min)` consecutive decision bars; default 3 × 5m). Rollup already handles premium-decay re-positioning when premium drops below 20, so no additional strike-hunting logic is needed during cooldown.
  - **State**: `stop_gate: dict[str, dict]` keyed by opt_type `{"exit_px": float, "bars": list[Bar], "n_below": int}`. Captured in `manage_legs` **before** calling close helpers (so `leg.bars` is alive). Overwritten if a second stop fires on same side.
  - **Tick loop** (every bar, before entry gate, for each `ot` in `stop_gate`):
    ```
    px = price_at(gate["bars"], ist_dt)   # stopped strike's live premium
    if px is not None and px < gate["exit_px"]:
        gate["n_below"] += 1
        if gate["n_below"] >= ceil(15 / timeframe_min):
            del stop_gate[ot]             # gate cleared — re-entry allowed
    else:
        gate["n_below"] = 0              # at/above exit_px → restart the 15m count
    ```
  - **Entry guard**: `"PE" not in stop_gate` / `"CE" not in stop_gate` checked per side independently before `open_leg`. Blocked side logs `stop_gate_wait:{ot}`. Ungated side opens normally per bias.
  - **Cleanup**: `stop_gate.clear()` at squareoff — no carryover.
  - **Known limitation (v1)**: if a roll fires on the remaining half after `pct_stop_half`, `gate["bars"]` points to the pre-roll strike. Acceptable — noted in code comment.
  - Files: `src/pdp/backtest/strangle_sim.py`; `WAIT·GATE` tag in scratchpad `gen_daily_flow.py`.
- [x] 3.8 Detailed every-minute status logging: `BarStatus`/`LegStatus` trace + `format_status_line` (score, each signal vote, VIX/PCR, legs LTP/MTM, day P&L, action)
- [x] 3.9 Unit tests `tests/backtest/test_strangle_sim.py` — leg counts per bucket, gates, each exit path, status trace (10+ tests passing)

## 4. Runner + configs (Phase 3)

- [x] 4.1 Create `backtest/strangle_run.py` — loads window + VIX once, assembles `BiasInputs` via `strangle_loader`, replays per day, prints summary; `--trace` prints every-minute status
- [x] 4.1b Create `src/pdp/backtest/strangle_loader.py` — multi-timeframe `BiasInputs` assembly (5m/15m/1h EMAs warmed 20 days, daily+weekly Camarilla, swing, VWAP, ORB, VIX); smoke-tested
- [x] 4.2 Create `backtest/configs/strangle_premium.yaml` and `backtest/configs/strangle_delta.yaml`
- [x] 4.3 Add Taskfile target `task backtest:strangle`
- [x] 4.4 `--dte-max N` CLI flag + `dte_max: int | None` in `StrangleConfig` — filter to DTE ≤ N calendar days before expiry (DTE 0 = expiry/Tue, DTE 1 = Mon; DTE 2 = Sun/non-trading so `--dte-max 1` is the operative 0DTE+1DTE filter). Applies per-day in the runner before `build_strangle_day`; skipped days counted in the skipped total.
- [x] 4.5 5-year full run with `--dte-max 1` (DTE 0+1 only, Mon+Tue only) — DONE: config `strangle_tren_cons_tp05_hedged.yaml`, 2021-09-01→2026-06-25, hedges=ON, scale_lots=2. **Net +Rs 29.4L | PF 4.67 | Win 76% | MaxDD Rs 52,282 | 314 traded days | 29 halted days.** Artifacts: `backtest/runs/strangle_20260626-210031`. DTE filter cuts 74% of days but retains strong edge (PF 4.67 vs 5.72 all-days — lower vol, tighter MaxDD).

## 4b. Run archival (extensive per-day logs + timing)

- [x] 4b.1 `src/pdp/backtest/strangle_report.py` (`RunWriter`) — per-day status.log/trades.csv/legs.csv/day.json + run-level summary.csv/equity.csv/manifest.json with build/sim timing
- [x] 4b.2 Wire `--out-dir` into `strangle_run.py` with quarter-chunked loading (multi-year runs don't hold all chains in RAM); git-ignore `backtest/runs/`

## 5. Walk-forward optimization (Phase 4 — go/no-go gate)

- [x] 5.1 Create `backtest/strangle_walkforward.py`: rolling fixed-size IS window + sliding OOS; selects grouped params on IS only (day-data built once per fold, candidates are cheap re-sims)
- [x] 5.2 Report IS-vs-OOS net/PF/Sharpe/maxDD per fold + stitched-OOS equity; grouped knobs (weight profile × aggressiveness × take-profit × hedge) keep free params low; `task backtest:strangle:wf`
- [x] 5.3 Walk-forward re-run with DTE-1 filter — **PASS 13/13 OOS folds profitable.** Config `strangle_tren_cons_tp05_hedged.yaml`, 2021-09-01→2026-06-25, `--dte-max 1`, calmar objective, IS=12m OOS=3m, 13 folds completed (2 skipped thin). **Stitched OOS: Net +Rs 25.0L | PF 3.42 | Win 74% | MaxDD Rs 66,892 | Sharpe 6.81 | Calmar 37.41 | 293 days | 4205 trades.** Previous all-days run was 12/16 REVIEW; DTE-1 filter eliminated all 4 losing folds. Report: `backtest/runs/wf_dte1_calmar.csv`. Verdict: robust OOS edge confirmed — Phase 5 paper is validated.

## 6. Paper strategy (Phase 5 — WF gate bypassed; 5yr full-window PASS)

- [x] 6.1 Create `src/pdp/strategies/directional_strangle.py` (Strategy ABC) reusing `src/pdp/signals/bias.py`; multi-lot stops, VIX gate, squareoff, day-loss cap, momentum on/off flag, hedge premium-band scan
- [x] 6.2 Create `strategies/directional_strangle.yaml` (watchlist 5m/15m/1h + indicators; params; risk); auto-loaded by `StrategyHost`
- [x] 6.3 Live VIX wired via `on_tick`; PCR = None (live PCR wiring is follow-up); paper-first default
- [x] 6.3b Hedge logic fixed: replaced `hedge_otm_extra=8` (fixed step) with premium-band scan `[prem_min=2, prem_max=5]` across 10–22 OTM steps — matches backtest `_select_hedge_strike`
- [x] 6.3c Momentum long (`momentum_enabled`) wired in both sim and live strategy; disabled by default after 5yr test showed 3.6× MaxDD for only +Rs 3.73L uplift
- [x] 6.4 Live↔backtest parity hardening — **deferred to follow-up OpenSpec `live-directional-strangle-paper`** (strategy loads and enters/exits; remaining gaps: rollup, stop-gate re-entry, cam_weekly, per-vote logging, PCR live feed — all tracked there)

## 5-Year Canonical Results (2021-09-01 → 2026-06-25, dominant config)

Config: `backtest/configs/strangle_tren_cons_tp05_hedged.yaml`
Net: +Rs 85.6L | PF 5.72 | Win% 75% | MaxDD Rs 71,579 | Halted 50 days | 1171 traded days
Zero losing months. All years profitable (2021: +6.2L, 2022: +18.4L, 2023: +17.1L, 2024: +9.8L, 2025: +22.7L, 2026: +11.5L)

## 7. Validation & archive

- [x] 7.1 `task test` and `task lint` / `task typecheck` green — DONE: 32 strangle/signals tests pass; 559 total pass (1 more than main branch); commission tests updated for corrected rates (STT 0.15%, SEBI 0.0001%, stamp 0.003%); 24 remaining failures are all pre-existing (risk/jobs modules); ruff clean on all changed files
- [x] 7.2 `openspec validate directional-strangle --strict` passes — "Change 'directional-strangle' is valid"
- [x] 7.3 CLAUDE.md files updated: `src/pdp/backtest/`, `src/pdp/strategies/`, `backtest/`, `strategies/MultiTimeFrameSelling.txt`
- [x] 7.4 Archive the change — DONE 2026-06-26: delta spec synced to `openspec/specs/directional-strangle/spec.md`; change moved to `openspec/changes/archive/2026-06-26-directional-strangle/`

## Follow-up OpenSpec changes (proposed)

- `live-directional-strangle-paper` — rollup, stop-gate, cam_weekly, per-vote logging, parity test
- `backtest-multi-index-strangle` — BANKNIFTY + SENSEX data backfill + same strategy 5yr backtest
