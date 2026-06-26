## 1. Data foundation & audit (Phase 0, Dhan → Mongo only)

- [ ] 1.1 Extend the NSE holiday calendar in `data/calendars/` to cover 2021–2022 — _needs the official NSE holiday dates (not guessed); missing entries are non-blocking (those days fall out as no-data skips via the completeness gate)_
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
- [ ] 2.5 Add an ORB helper (15m opening range from the first 15m bar) usable by both backtest and live — _votes wired; opening-range computation helper still to add in sim/live adapters_
- [x] 2.6 Unit tests `tests/signals/test_bias.py` — table-driven per-signal votes, each bucket, both gates, determinism (16 tests passing)

## 3. Multi-leg ratio-strangle simulator (Phase 2)

- [x] 3.1 Create `src/pdp/backtest/strangle_config.py` (`StrangleConfig` dataclass: bias weights, gate thresholds, `strike_method`, ratio table, stops, `take_profit_pct`, `roll_trigger_prem`, `roll_target_min_prem`, session windows; `from_yaml`/`from_dict`)
- [x] 3.2 Create `src/pdp/backtest/strangle_sim.py` — pure engine consuming pre-assembled per-bar `BiasInputs`; legs keyed by opt_type with per-bucket lot ratio
- [x] 3.3 Wire the bias engine to set per-bar bucket → PE:CE leg counts; gate entries until after the 10:15 1h candle
- [x] 3.4 Implement `strike_method=premium` (most-OTM strike with premium > floor; ATM at extreme buckets)
- [ ] 3.5 Implement `strike_method=delta` (solve IV from premium, use `src/pdp/options/greeks.py` for 0.6Δ targeting) — _scaffolded; currently falls back to premium method, TODO to wire IV solve_
- [ ] 3.6 Implement PCR per bar from `option_bars` OI (reuse `compute_pcr` in `src/pdp/options/analytics.py`) and join the VIX series per day — _consumed via `BiasInputs`; loader to populate (Phase 0/3)_
- [x] 3.7 Implement exits: rollup (<20), take-profit (% credit), tiered premium stop, trend-flip adjustment (bias sign flip), ₹15,000 daily-loss cap, session square-off
  - Tiered premium stop (`pct_stop_enabled`): 30% above entry → close half lots (`pct_stop_half`); 40% above entry → close all remaining (`pct_stop_all`). Replaced the 2x premium-doubled rule. 30-day result: Net +64,210 / PF 2.06 / Win 64% vs +8,589 / 1.13 / 52% before.
  - Squareoff missing-price fix: `close_leg` now falls back to `_last_price(bars, ist_dt)` when `price_at` returns None (deep-OTM strikes with no bars near squareoff); final fallback ₹0.01 (expired worthless). Day 3 (2026-05-20) PE@23000 was the trigger — fixed +₹8.8k recovery.
- [x] 3.7b Protective hedges (defined-risk spreads): per short leg, buy a far-OTM long in the [2,5]₹ band (else cheapest available wing); rides the leg lifecycle (open/roll/close); `--hedge/--no-hedge` runner override + `strangle_*_hedged.yaml` configs. A/B (May–Jun 2026): hedged PF 1.86 vs naked 1.45, MaxDD −29%.
- [ ] 3.7c **PLANNED** — Stop-recovery re-entry gate (15m sustained below exit price)
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
- [ ] 4.5 **IN PROGRESS** — 5-year full run with `--dte-max 1` (DTE 0+1 only): focuses on Monday+Tuesday sessions where theta decay is fastest and premium levels are still tradeable.

## 4b. Run archival (extensive per-day logs + timing)

- [x] 4b.1 `src/pdp/backtest/strangle_report.py` (`RunWriter`) — per-day status.log/trades.csv/legs.csv/day.json + run-level summary.csv/equity.csv/manifest.json with build/sim timing
- [x] 4b.2 Wire `--out-dir` into `strangle_run.py` with quarter-chunked loading (multi-year runs don't hold all chains in RAM); git-ignore `backtest/runs/`

## 5. Walk-forward optimization (Phase 4 — go/no-go gate)

- [x] 5.1 Create `backtest/strangle_walkforward.py`: rolling fixed-size IS window + sliding OOS; selects grouped params on IS only (day-data built once per fold, candidates are cheap re-sims)
- [x] 5.2 Report IS-vs-OOS net/PF/Sharpe/maxDD per fold + stitched-OOS equity; grouped knobs (weight profile × aggressiveness × take-profit × hedge) keep free params low; `task backtest:strangle:wf`
- [ ] 5.3 Run the optimizer over the full window and record the decision (proceed to Phase 5 only if stitched OOS is robustly profitable).
  - Previous run (all-days, calmar objective, 16 folds IS=12m OOS=3m): stitched OOS net +314,953 / PF 1.11 / maxDD 195,593 / sharpe 0.47 / positive folds 12/16 → **REVIEW** (not PASS).
  - Blocking issues: 4 losing OOS folds (folds 7,9,10,14) concentrated in 2024 trending-bull markets; shape/drawdown unacceptable even where net is positive. Next lever = DTE filter (0DTE+1DTE only) + stop-recovery gate (3.7c) before re-running OOS.

## 6. Paper strategy (Phase 5 — only if 5.3 passes)

- [ ] 6.1 Create `src/pdp/strategies/directional_strangle.py` (Strategy ABC) reusing `src/pdp/signals/bias.py`; multi-lot scale-in/out + stops following `supertrend_short.py` patterns
- [ ] 6.2 Create `strategies/directional_strangle.yaml` (watchlist 5m/15m/1h/1d/1w + indicators; params; risk); auto-loaded by `StrategyHost`
- [ ] 6.3 Wire live VIX + PCR reads; paper-first (`LIVE` unset)
- [ ] 6.4 Live↔backtest parity check on a same-day replay; run a paper session and confirm via `task monitor`

## 7. Validation & archive

- [ ] 7.1 `task test` and `task lint` / `task typecheck` green
- [ ] 7.2 `openspec validate directional-strangle --strict` passes
- [ ] 7.3 Update affected `CLAUDE.md` indexes (`src/pdp/backtest`, `src/pdp/strategies`, `strategies/`, `scripts/`) for the new files
- [ ] 7.4 Archive the change: `openspec archive directional-strangle`
