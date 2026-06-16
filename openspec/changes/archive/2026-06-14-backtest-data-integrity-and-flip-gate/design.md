## Context

`backtest_multiday.py` reads NIFTU index 1m bars from `market_bars` (`security_id="13"`,
`timeframe="1m"`), resamples to 5m, and feeds a `SuperTrendTracker(period=3, multiplier=1)` to
generate option-selling signals. The local `market_bars` is a cache that is frequently incomplete
for the index, while Dhan holds the full history. The options warehouse (`option_bars`) is
separately well-covered for the audited window but is derived from the index close, so any spot
backfill must precede option backfill.

## Goals

- Never produce backtest P&L from incomplete spot data — skip and label such days.
- Make missing NIFTU spot history recoverable and idempotently re-runnable.
- Anchor each day's first entry to a genuine SuperTrend flip, not the cold-start direction.

## Decisions

### Backfill source and schema (Part A)
- Use `dhan.intraday_minute_data(security_id="13", exchange_segment="IDX_I", instrument_type="INDEX", interval=1)`.
- Timestamps are epoch seconds; store as **UTC-naive** (`datetime.utcfromtimestamp(epoch)`) to match
  the existing `market_bars` schema (verified: existing 09:15 bar is `ts=03:45 UTC`, naive).
- **Upsert** keyed on `(ts, metadata.security_id, metadata.timeframe)` — idempotent; complete days
  are untouched, holes are filled.
- Reuse `src/pdp/indicators/warmup.py` `_fetch_from_dhan` (already handles the `IDX_I`→`INDEX`
  mapping and epoch parsing) and `_persist_bars` (writes the exact doc shape) rather than
  re-implementing.
- Throttle to the Data-API limit (5 req/sec); chunk ≤ 90 days/call; back off on `DH-904`.

### Completeness gate (Part C)
- A day passes when its NIFTU 1m series has ≥ `MIN_BARS_FRAC` of the expected ~375 session bars
  **and** no intraday gap ≥ `MAX_GAP_MIN` minutes (defaults: 0.95 and 5). These are module
  constants so they can be tuned without code edits scattered around.
- A failing day yields a `data_incomplete` result object (zero trades, carries the diagnostic
  reason) so the summary can render it distinctly. The backtest **does not** fall back to the Dhan
  API mid-run for the index — backfill is an explicit, auditable step, not a hidden hot-path fetch
  (consistent with CLAUDE.md "no blocking calls on the hot path").

### First-flip gate (Part D)
- `SuperTrendState.flipped` is already True only on a genuine direction change
  (`src/pdp/indicators/supertrend.py:140`). A per-day `first_flip_seen` flag (reset at each day's
  start) gates new entries: while False, no open/scale-in occurs; it is set on the first post-start
  bar with `st.flipped`, after which entry behavior is normal.
- This is independent of the data fix but must be validated **after** it — on gapped data the first
  flip is artificially late (11:35 on 2026-06-12); on complete data the early Kite flips
  (~09:50/10:55) appear and the gate fires early.

## Sequencing

Spot backfill (A) → options backfill (B) → gate (C) → flip gate (D). B depends on A because option
strike resolution reads the index 1m close at the same minute.

## Risks / trade-offs

- **Rate limits:** deep-history backfill can hit `DH-904`; mitigated by throttling + chunking +
  backoff. Re-runs are safe (idempotent upsert).
- **Skipping days reduces sample size:** acceptable — trustworthy fewer days beats fabricated P&L.
  After backfill, few or no days should be skipped.
- **First-flip gate forgoes early-session moves on clean trend days:** intended; the reverse-bias
  premium-selling strategy prefers an established direction over the noisy open.
