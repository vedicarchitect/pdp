## 1. R1 — Route live option LTP to the strategy

- [ ] 1.1 Add a per-running-strategy dynamic SID set to `StrategyHost` (alongside running state)
- [ ] 1.2 `MarketControl.subscribe()`/`unsubscribe()` in `pdp/strategy/context.py` notify the host to
  add/remove the SID for the current strategy
- [ ] 1.3 `StrategyHost.on_tick()` dispatch matches static watchlist **∪** dynamic set
  (`_watches_security` or equivalent)
- [ ] 1.4 Clear a SID on leg close in `directional_strangle.py` (short/hedge/momentum close paths),
  and clear the whole dynamic set on strategy stop
- [ ] 1.5 Unit test: a runtime-subscribed SID's tick reaches `strategy.on_tick` and populates
  `_ltp_cache`; stop clears the set

## 2. R2 — Paper fill integrity / no fabricated losses

- [ ] 2.1 Paper MARKET fill in `pdp/orders/paper.py` uses cached Redis `ltp:<sid>` at placement;
  never persists `avg_price = 0` (leave pending + retry if no price yet)
- [ ] 2.2 `upsert_position` guards `old_avg == 0` on reduce/close: skip the realized contribution
  (treat as 0) and `log.warning`
- [ ] 2.3 Add `_record_day_baseline(sid)` to `_open_hedge` in `directional_strangle.py` (parity with
  `_open_short` and `_open_momentum`)
- [ ] 2.4 `_await_fill_avg_px` becomes a fallback; flag/log a zero return as anomalous
- [ ] 2.5 Unit tests: (a) zero-average short close yields 0 realized; (b) MARKET fill uses cached
  LTP and never persists avg=0

## 3. R5 — Day-loss halt survives restart

- [ ] 3.1 Persist a halt marker keyed by `strategy_id + IST day` when `day_loss_cap` fires
  (Redis key via existing client, or a small PG row)
- [ ] 3.2 On strategy start, if the marker is set for today, initialise `_done_for_day = True`
- [ ] 3.3 Clear the marker on IST date rollover (`_maybe_reset_day`)
- [ ] 3.4 Unit test: marker blocks re-entry on same-day restart; clears next IST day

## 4. R3 — Full bias signal set

- [ ] 4.1 `pcr`: expose a PCR reading from the option-chain poller (`pdp/options/`); feed
  `BiasInputs.pcr` in `_build_bias_inputs`
- [ ] 4.2 `cam_weekly`: add `1w` timeframe support so `ind.pivots(sid, "1w")` returns a weekly pivot
  snapshot; add `1w` to the strangle YAML watchlist
- [ ] 4.3 `ema_1h` / `ema_15m`: fix warmup seeding so the 50-bar EMA values dict is populated for
  15m/1h before the first bar (`pdp/indicators/warmup.py`)
- [ ] 4.4 `vwap`: compute from index **futures** volume (front-month) instead of the volume-less
  index spot; surface via `ind.vwap` or an equivalent the bias engine reads
- [ ] 4.5 Verify each vote is emitted when its input is present (no silent drop) in `bias.py`
- [ ] 4.6 Unit/integration test: with warmup + chain available, `votes` contains all 9 signals

## 5. R4 — Bucket-change hysteresis

- [ ] 5.1 Add `bucket_confirm_bars` param (default 2) to strangle params + YAMLs
- [ ] 5.2 At the bucket-change site in `directional_strangle.on_bar` track pending bucket + counter;
  only close/reopen after N consecutive bars; reset on revert
- [ ] 5.3 Unit test: single-bar flip does not churn; N-bar sustained change acts

## 6. Validation + docs + archive

- [ ] 6.1 `task openspec:validate -- strangle-live-paper-hardening --strict` passes
- [ ] 6.2 `task lint && task typecheck` — no new items; `task test` — no new failures (baseline 27)
- [ ] 6.3 `docs/RUNBOOK.md` — LTP-delivery path, halt persistence, signal wiring notes
- [ ] 6.4 Owner paper smoke (next session, `LIVE=0`): leg_status ltp/mtm non-null; all entry prices
  > 0 incl. hedges; votes contain all 9 signals; no sub-15-min bucket reversal churn; restart after
  a simulated cap does not re-enter
- [ ] 6.5 `task reset-paper` after close to clear today's bug-corrupted PG positions
- [ ] 6.6 Archive: `task openspec:archive -- strangle-live-paper-hardening`
