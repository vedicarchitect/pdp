## 1. NIFTU spot backfill script (Part A)

- [x] 1.1 Create `scripts/backfill_nifty_spot.py` with argparse (`--from`, `--to`, `--only-missing`, `--dry-run`), `.env` credential load via `pdp.settings.get_settings`, and structlog — mirroring `scripts/backfill_options_gap.py`
- [x] 1.2 Fetch NIFTU index 1m bars from Dhan (`security_id="13"`, `exchange_segment="IDX_I"`, `instrument_type="INDEX"`, `interval=1`); convert epoch → UTC-naive. (Self-contained fetch: `warmup._fetch_from_dhan` hardcodes a yesterday/today window, so the historical-range fetch is inlined.)
- [x] 1.3 Chunk requests to ≤ 90 days/call and throttle to ≤ 5 requests/sec with backoff on `DH-904` rate-limit
- [x] 1.4 Write into `market_bars` keyed on the trade day so existing complete days are not duplicated. (`market_bars` is a MongoDB **time-series** collection — upsert/non-multi update is rejected (code 72); idempotency is delete-the-day-then-insert.)
- [x] 1.5 `--dry-run` prints the planned trade-day range without requiring Dhan credentials; `--only-missing` skips days already at expected bar count
- [x] 1.6 Run `pyright scripts/backfill_nifty_spot.py` — only the project-baseline third-party-stub errors remain (dhanhq has no stubs; pymongo `Collection[Unknown]`), identical to the sibling `backfill_options_gap.py`

## 2. Run backfills (Parts A + B, in order)

- [x] 2.1 Run `python scripts/backfill_nifty_spot.py --from 2026-06-04 --to 2026-06-12` (spot first) — 2,625 rows written, 375/day
- [x] 2.2 Re-run the completeness audit — all 7 days reach 375 NIFTU 1m bars (09:15–15:30, span 03:45→09:59 UTC) with max intraday gap 1 min; `--only-missing` re-run confirms idempotency (0 to fill)
- [x] 2.3 Run `python scripts/backfill_options_gap.py --from 2026-06-04 --to 2026-06-12 --only-missing` (options, after spot) — `gaps=0`, nothing to fill
- [x] 2.4 `option_bars` coverage confirmed: ~21,000 bars/day across all 7 days (already structurally complete for the window)

## 3. Data-completeness gate (Part C)

- [x] 3.1 Completeness logic lives in `pdp.backtest.completeness.spot_completeness` (importable, unit-tested) with module constants `EXPECTED_SESSION_BARS=375`, `MIN_BARS_FRAC=0.95`, `MAX_GAP_MIN=5`; called from `simulate_day()` before the bar loop on the raw 1m series
- [x] 3.2 Failing day returns a `data_incomplete` result (no trades) carrying `reason`, `nifty_bars`, `max_gap_min`
- [x] 3.3 `data_incomplete` surfaced distinctly in `print_day` and the final summary table (excluded from P&L/win-rate aggregation, counted separately)
- [x] 3.4 `spot_completeness` log line per day reports bar count, max gap, and ok flag

## 4. Wait-for-first-flip entry gate (Part D)

- [x] 4.1 `simulate_day()`'s bar loop has a per-day `first_flip_seen` flag (reset each day; it is a local), set True on the first bar after `start_dt` where `st.flipped` is True
- [x] 4.2 New-position entries (open + scale-in) suppressed while `first_flip_seen` is False; leg-stop, flip-close, and square-off logic unchanged
- [x] 4.3 Normal entry resumes from the first-flip bar onward

## 4b. Continuous cross-day SuperTrend warmup

- [x] 4b.1 Add `_prior_session_5m(trade_date)` in `backtest_multiday.py` — resampled 5m bars for the most recent prior trading day (walks back over weekends/holidays / no-data days)
- [x] 4b.2 In `simulate_day()`, warm the fresh tracker with the prior session's bars before feeding the day's bars; warmup bars are fed but NOT emitted into `series`, so the day's first `flipped` is a real carried-over-direction change, not a cold-start artifact
- [x] 4b.3 Verify on 2026-06-12: tracker enters UP (from 06-11's uptrend), holds GREEN through the gap-up, flips UP→DOWN at ~09:55 (matching Kite), so the first trade opens at 09:55 SELL CE — not 10:55

## 5. Tests

- [x] 5.1 `tests/backtest/test_data_integrity.py`: complete day passes; day with a > `MAX_GAP_MIN` hole is incomplete; zero-bar day is incomplete; too-few-bars is incomplete; just-above-threshold passes
- [x] 5.2 First-flip-gate tests: first bar never flips; a sustained move flips off the cold-start seed; the gate stays unarmed before the first flip and arms exactly on the flip bar
- [x] 5.2b Warmup-continuity tests: a rising prior session carries UP into the open (continuation, not a flip); a prior-up-then-morning-fall flips UP→DOWN at the open window
- [x] 5.3 `pytest tests/backtest/test_data_integrity.py -v` — 10 passed (full `tests/backtest/` suite: 16 passed)

## 6. End-to-end verification

- [x] 6.1 `uv run python backtest_multiday.py --days 7 --start 2026-06-12` — all 7 days simulated, 0 `data_incomplete`; previously zero-spot days (06-04/05/11) now produce data-backed results. (Verified the gate fires by punching a synthetic 30-min hole in 06-10 → reported `data_incomplete`, then restored.)
- [x] 6.2 On 2026-06-12, re-dumped SuperTrend bar-by-bar — direction is DOWN from the open (NIFTY genuinely drifts down 23401→23358), first genuine flip to UP at **10:55** (matching Kite); the first trade now opens at 10:55, not 11:35. (No 09:50 flip exists — that Kite move was a down-continuation, not a direction change.)
- [x] 6.3 `openspec validate --strict backtest-data-integrity-and-flip-gate` — valid
