## Context

The PDP currently supports live strategy execution with event-driven callbacks (on_bar, on_tick, etc.) feeding real market data to Strategy instances. To validate strategy logic before deploying to live trading, we need a backtest engine that:

- Replays historical market data from MongoDB `market_bars`
- Reuses the exact same `Strategy` interface and hooks as live
- Produces comparable trade logs and equity curves
- Requires minimal duplicate logic between live and backtest paths

## Goals / Non-Goals

**Goals:**
- Backtest engine that reuses the live `Strategy` interface without modification
- Historical bar/tick replay from MongoDB with event-driven loop identical to live
- Pre-computed indicators (via Polars vectorization) cached per (security, timeframe) to avoid recomputation
- Output three tables (`backtest_runs`, `backtest_trades`, `backtest_daily`) + CSV export to `backtest/results/`
- CLI command: `pdp backtest run <strategy_id> --from <date> --to <date>`
- Equity curve and trade-level outputs comparable to live trading

**Non-Goals:**
- Multi-worker backtest parallelization (single-threaded replay initially)
- Portfolio-level backtests spanning multiple strategies
- Walk-forward optimization or parameter sweeps
- Transaction cost modeling or slippage simulation

## Decisions

### 1. Reuse Strategy Interface via Time Mock
**Decision:** Backtest mode runs the same `Strategy` code as live, using a time-mocked context that replays historical bars instead of forwarding live ticks.

**Rationale:** Eliminates duplicate strategy logic and ensures backtest results reflect actual strategy behavior. Single source of truth for strategy rules.

**Alternatives Considered:**
- Separate backtest strategy parser: Higher maintenance burden, risk of logic divergence
- Simulating vs. replaying: Simulation loses order-of-events fidelity that live depends on

---

### 2. Indicator Pre-computation & Caching
**Decision:** Pre-compute all indicators once per (security, timeframe) using Polars vectorization over the entire historical window, cache in memory or Redis, and serve lookups during bar replay.

**Rationale:** Avoids recomputing the same indicators millions of times during replay. Shared infrastructure with live mode (universal indicators per spec non-negotiable #4).

**Alternatives Considered:**
- On-demand indicator computation per bar: High latency, violates latency spec (p99 ≤ 50ms)
- Store indicators in MongoDB: Network latency; vectorized pre-compute is faster and memory-bounded

---

### 3. Event-Driven Loop Unchanged
**Decision:** Backtest uses the same `BarArrived` / `TickArrived` event loop as live, with a history cursor advancing instead of a live WebSocket connection.

**Rationale:** Guarantees identical hook execution order and timing logic. No special-case code paths in strategy execution.

**Alternatives Considered:**
- Bulk vectorized strategy application: Loses event ordering; strategies depend on precise tick/bar sequence
- Separate backtest event scheduler: Duplicate scheduling logic; diverges from live behavior

---

### 4. Storage Architecture
**Decision:** Store results in PostgreSQL (`backtest_runs`, `backtest_trades`, `backtest_daily` tables), with JSON columns for config snapshots and CSV export to local filesystem.

**Rationale:** Structured schema for filtering/aggregation; PostgreSQL dual-writes with ledger pattern; CSV for ad-hoc analysis and archive.

**Alternatives Considered:**
- MongoDB only: Loses relational consistency for run metadata
- Parquet files: Add Parquet dependency; CSV is sufficient for analysis and simpler to manage

---

### 5. Time Handling
**Decision:** Backtest injects a `SimulatedClock` into the strategy context that returns the current bar's timestamp. All `datetime.now()` calls in strategy code see the simulated time.

**Rationale:** Strategies using date comparisons (e.g., "skip on Friday close") behave identically to live.

**Alternatives Considered:**
- Global datetime patch: Too invasive; hard to test live + backtest together
- Strategy-aware time API: Requires strategy changes; violates reuse goal

---

### 6. Order Execution Model
**Decision:** Backtest uses a simplified execution model: orders fill immediately at bar close (OHLC), no partial fills, no slippage. Rejects orders if they violate position limits.

**Rationale:** Conservative default; strategies can add their own slippage/fill logic if needed. Paper mode already has this model.

**Alternatives Considered:**
- Tick-level fill simulation: Too slow for large backtests; adds complexity for marginal realism
- Limit order book: Requires intrabar order flow data we don't have

---

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **Incomplete market_bars history** — Missing bars for a security/date range skew results | Validate input date range against available history; warn user of gaps |
| **Indicator divergence** — New indicator added to live but not pre-computed for backtest window | Document requirement that all indicators must support vectorized pre-compute; CLI validates indicator coverage |
| **Memory spike on large backtests** — Pre-computing all indicators over 5 years of data exhausts RAM | Implement chunked processing by date range; support incremental indicator compute |
| **Paper mode execution vs. backtest** — Paper mode may not match backtest due to timing assumptions | Ensure both modes use same order execution model; backtest inherits paper mode's fill rules |
| **Equity curve doesn't match reality** — Commission, slippage, market hours gaps introduce error | Document all assumptions; provide CSV output for user reconciliation against live if traded |

## Migration Plan

1. **Phase 1 (MVP):** Implement single-strategy backtest on local market_bars (no parallel workers).
2. **Phase 2:** Expose CLI (`pdp backtest run <strategy_id> --from --to`), verify indicator pre-compute works.
3. **Phase 3:** Output tables + CSV export; schema stabilization.
4. **Phase 4 (Future):** Multi-strategy, portfolio backtests, parameter sweeps.

## Open Questions

- Should backtest support multiple timeframes for the same security, or collapse to a single bar timeframe?
- How to handle corporate actions (splits, dividends) in historical market_bars?
- Should backtest log all orders (including rejected ones) or only fills?
