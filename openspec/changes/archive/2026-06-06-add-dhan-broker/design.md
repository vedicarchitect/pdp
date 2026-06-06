## Context

The `order-execution` capability ships a working paper engine: `OrderRouter` validates and persists orders, `PaperBroker` fills them from the Redis tick stream, and positions/charges are accounted on each fill. `select_broker()` already returns `("dhan", LIVE)` when `LIVE=1` and `BROKER=dhan`, but there is no live adapter to receive those orders. This change adds `DhanBroker`, mirroring the `PaperBroker` interface so the router stays broker-agnostic.

Key constraints:
- The `dhanhq` SDK is **synchronous** (REST methods block); it must never run on the asyncio event loop directly.
- The Dhan order-update feed (`OrderSocket`) is a blocking/threaded loop, like the existing `DhanTickerAdapter` market feed.
- **Paper-first** is non-negotiable: live activation requires explicit `LIVE=1`, `BROKER=dhan`, and credentials.
- Orders/trades/positions stay in PostgreSQL; this change is independent of the MongoDB warehouse migration.

## Goals / Non-Goals

**Goals:**
- A `DhanBroker` with the same interface as `PaperBroker` (`start`/`stop`/`add_order`/`cancel_order`/`set_hub`).
- Place/cancel orders via Dhan REST; persist `broker_order_id`; correlate via `tag = client_order_id`.
- Convert live fills (order-update `TRADED` + trade book) into `Trade`/`Position` rows reusing paper accounting, and publish to `/ws/orders`.
- Startup reconciliation of fills missed while the process was down.
- Real Dhan cost rows so live charges are accurate.

**Non-Goals:**
- Order modification (`modify_order`) — cancel + re-place is sufficient for v1.
- Bracket/cover/MTF product types — only NRML/MIS/CNC mapped initially.
- Multi-account support; a single Dhan client is assumed.
- Any change to paper-engine behavior or the mode-gate header contract.

## Decisions

**1. Mirror the `PaperBroker` interface rather than abstracting a base class.**
The router only needs duck-typed `add_order`/`cancel_order`/`set_hub`. Mirroring keeps the diff small and avoids refactoring the shipped paper path. *Alternative considered:* extract a `Broker` Protocol — deferred; can be introduced later without behavior change.

**2. Run all `dhanhq` REST calls in `loop.run_in_executor(None, ...)`.**
The SDK is synchronous; offloading to the default thread pool keeps the event loop unblocked (latency budget). *Alternative:* a custom httpx async client reimplementing Dhan endpoints — rejected as duplicative and fragile vs. the maintained SDK.

**3. Bridge `OrderSocket` with the same thread→loop pattern as `DhanTickerAdapter`.**
Run the blocking socket in a worker thread and hand events back via `loop.call_soon_threadsafe`. Reuses a proven pattern in `src/pdp/market/dhan_ws.py`. *Alternative:* poll the order book on an interval — rejected (latency, rate limits, missed transient states).

**4. Source fill price/qty from the trade book, not the order-update payload.**
The `TRADED` alert signals a fill but the authoritative price/qty come from `get_trade_book(broker_order_id)`. This avoids partial-fill ambiguity in the alert and matches how positions must be accounted.

**5. Reuse paper-engine position/charge logic.**
Factor the `_upsert_position` + `ChargesCalculator` usage so both brokers share weighted-average / realize-on-reduce accounting and the `broker_costs`-driven cost model. Guarantees identical P&L semantics across paper and live.

**6. Correlate via Dhan `tag = client_order_id`; key local lookups by `broker_order_id`.**
`tag` rides round-trip so we can match an alert to our order even before `broker_order_id` is persisted; once stored, `broker_order_id` is the primary join key for updates and reconciliation.

## Risks / Trade-offs

- **Process downtime causes missed fills** → startup reconciliation (`get_order_list` + `get_trade_book`) replays anything not recorded locally before resuming the live stream.
- **Partial fills** → trade-book fetch sums executed qty; a single `Trade` row per reconciliation pass is created per new fill, and position accounting is additive so repeated passes are idempotent on `broker_order_id` + trade id.
- **SDK thread-pool exhaustion under burst** → REST calls are short-lived; if needed, a dedicated bounded executor can replace the default pool (out of scope now).
- **Cost-table drift vs. real Dhan charges** → seeded from published NSE/BSE schedules; charges are best-effort and reconciled against broker contract notes later.
- **Accidental live trading** → triple-gated (`LIVE` + `BROKER=dhan` + credentials) and `X-Trade-Mode: LIVE` header makes the active mode visible on every response.

## Migration Plan

1. Apply migration `0007`: add nullable `orders.broker_order_id`; seed `broker_costs` for `dhan`. Backward compatible (nullable column, additive rows).
2. Deploy with paper defaults — no behavior change until `LIVE=1 BROKER=dhan` + credentials are set.
3. Live smoke: place a single small MARKET order, confirm on the Dhan dashboard, restart to verify reconciliation.
4. Rollback: unset `LIVE`/`BROKER` to revert to paper; migration `0007` is safe to leave in place (column nullable, rows unused by paper).

## Open Questions

- Should `modify_order` be supported, or is cancel + re-place acceptable long-term? (Currently Non-Goal.)
- Do we need a dedicated executor for REST calls, or is the default thread pool sufficient at expected order rates?
