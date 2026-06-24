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
- [x] 3.7 Implement exits: rollup (<20), take-profit (% credit), premium-doubled stop, trend-flip adjustment (bias sign flip), ₹15,000 daily-loss cap, session square-off
- [x] 3.7b Protective hedges (defined-risk spreads): per short leg, buy a far-OTM long in the [2,5]₹ band (else cheapest available wing); rides the leg lifecycle (open/roll/close); `--hedge/--no-hedge` runner override + `strangle_*_hedged.yaml` configs. A/B (May–Jun 2026): hedged PF 1.86 vs naked 1.45, MaxDD −29%.
- [x] 3.8 Detailed every-minute status logging: `BarStatus`/`LegStatus` trace + `format_status_line` (score, each signal vote, VIX/PCR, legs LTP/MTM, day P&L, action)
- [x] 3.9 Unit tests `tests/backtest/test_strangle_sim.py` — leg counts per bucket, gates, each exit path, status trace (10+ tests passing)

## 4. Runner + configs (Phase 3)

- [x] 4.1 Create `backtest/strangle_run.py` — loads window + VIX once, assembles `BiasInputs` via `strangle_loader`, replays per day, prints summary; `--trace` prints every-minute status
- [x] 4.1b Create `src/pdp/backtest/strangle_loader.py` — multi-timeframe `BiasInputs` assembly (5m/15m/1h EMAs warmed 20 days, daily+weekly Camarilla, swing, VWAP, ORB, VIX); smoke-tested
- [x] 4.2 Create `backtest/configs/strangle_premium.yaml` and `backtest/configs/strangle_delta.yaml`
- [x] 4.3 Add Taskfile target `task backtest:strangle`
- [ ] 4.4 Run the full audited window for both strike methods; confirm completion + sane metrics — _needs Phase-0 data_

## 5. Walk-forward optimization (Phase 4 — go/no-go gate)

- [ ] 5.1 Create `backtest/strangle_walkforward.py`: rolling IS/OOS split over the audited window; optimize weights/thresholds/strike params on IS only
- [ ] 5.2 Report IS-vs-OOS PF/Sharpe/max-DD side by side; constrain free-parameter count (grouped weights)
- [ ] 5.3 Produce the OOS report and record the decision (proceed to Phase 5 only if OOS is robustly profitable)

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
