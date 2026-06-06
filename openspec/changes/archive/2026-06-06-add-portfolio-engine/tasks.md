## 1. Settings and MongoDB collection

- [x] 1.1 Add `PORTFOLIO_MTM_INTERVAL_SECONDS: int = 5` and `PORTFOLIO_EOD_SNAPSHOT: bool = True` to `src/pdp/settings.py`
- [x] 1.2 Add `_ensure_portfolio_snapshots(db, ttl_days=90)` in `src/pdp/mongo/collections.py` — regular collection, TTL on `snapshot_ts` (90 days), unique index on `snapshot_date`; call from `init_collections()`

## 2. Portfolio package skeleton

- [x] 2.1 Create `src/pdp/portfolio/__init__.py` (empty)
- [x] 2.2 Create `src/pdp/portfolio/models.py` — `PositionState` dataclass: `security_id`, `exchange_segment`, `product`, `net_qty` (int), `avg_price` (Decimal), `realized_pnl` (Decimal), `unrealized_pnl` (Decimal), `updated_at` (datetime), `ltp_stale` (bool, default False), `mode` (str)

## 3. PortfolioHub

- [x] 3.1 Create `src/pdp/portfolio/hub.py` — `_PortfolioClient` with `asyncio.Queue(maxsize=20)` and drop-oldest `push()` logging `portfolio_client_lagging`; `PortfolioHub.broadcast(payload: list[dict])` serialises and sends to all clients; `PortfolioHub.make_client(ws)` factory; `PortfolioHub.add(client)` / `PortfolioHub.remove(client)`

## 4. PortfolioService

- [x] 4.1 Create `src/pdp/portfolio/service.py` — `PortfolioService.__init__(redis, db_engine, hub, settings)` with `_cache: dict[tuple, PositionState]` and `_dirty: set[tuple]`
- [x] 4.2 Implement `_load_positions(session)` — SELECT all positions from PG, populate `_cache`; called on `start()`
- [x] 4.3 Implement `_run_tick_listener()` — asyncio task: subscribes Redis pubsub to `tick.<sid>` for all held securities; on message parses `ltp`, recomputes `unrealized_pnl`, marks dirty, calls `hub.broadcast()`; uses `asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=1.0)` pattern for clean shutdown
- [x] 4.4 Implement `_run_flush()` — asyncio task: every `MTM_INTERVAL_SECONDS` writes dirty positions to PG via `UPDATE positions SET unrealized_pnl=:v, updated_at=:now WHERE id=:id` for each dirty entry; clears dirty set after flush
- [x] 4.5 Implement `_run_eod_snapshot()` — asyncio task: checks IST time every 60s; at 15:36 writes MongoDB snapshot doc (only once per day); respects `PORTFOLIO_EOD_SNAPSHOT` setting
- [x] 4.6 Implement `subscribe_fill_events(orders_hub)` — registers a callback on `OrdersHub` position events; on position event reloads PG row into cache, re-subscribes tick channel if new security; called in `main.py` after both hubs are wired
- [x] 4.7 Implement `start()` / `stop()` — launch the three asyncio tasks; `stop()` sets stop event and awaits all tasks

## 5. REST routes

- [x] 5.1 Create `src/pdp/portfolio/routes.py` with `router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])`
- [x] 5.2 Implement `GET /positions` — reads from PG via AsyncSession; optional `?mode=` filter; returns `{"positions": [...], "count": int}`; each position dict includes `security_id`, `exchange_segment`, `product`, `net_qty`, `avg_price`, `realized_pnl`, `unrealized_pnl`, `updated_at`
- [x] 5.3 Implement `GET /summary` — aggregates all positions from PG: `total_unrealized_pnl`, `total_realized_pnl`, `day_pnl` (sum of both), `open_positions` (count where net_qty ≠ 0), `mode` (paper/live/mixed based on distinct modes present)

## 6. WebSocket endpoint

- [x] 6.1 Create `src/pdp/portfolio/ws.py` — `GET /ws/portfolio`; on connect push initial snapshot from in-memory cache; then drain client queue in a pump loop; handle disconnect gracefully; remove client from hub on exit

## 7. Wire into main.py

- [x] 7.1 Import `PortfolioHub`, `PortfolioService`, `portfolio_router`, `portfolio_ws_router` in `src/pdp/main.py`
- [x] 7.2 In lifespan after `options_hub`: instantiate `PortfolioHub()`, store as `app.state.portfolio_hub`
- [x] 7.3 Instantiate `PortfolioService(redis, engine, portfolio_hub, settings)`, call `start()`, store as `app.state.portfolio_service`; on shutdown call `portfolio_service.stop()`
- [x] 7.4 Call `portfolio_service.subscribe_fill_events(orders_hub)` after both hubs are ready
- [x] 7.5 Register `portfolio_router` and `portfolio_ws_router` in `create_app()`

## 8. Tests

- [x] 8.1 `tests/portfolio/test_service.py` — `test_mtm_recomputed_on_tick()`: create a `PositionState` with net_qty=1, avg_price=22000; send mock tick ltp=22500; assert unrealized_pnl=500
- [x] 8.2 `tests/portfolio/test_service.py` — `test_ltp_stale_flag()`: after a tick arrives then expires (no new tick), assert `ltp_stale=True` on the next broadcast
- [x] 8.3 `tests/portfolio/test_hub.py` — `test_broadcast_delivered_to_client()` and `test_queue_overflow_drops_oldest()`
- [x] 8.4 `tests/portfolio/test_routes.py` — `test_positions_empty_returns_200()`, `test_positions_returns_rows()`, `test_summary_aggregates_pnl()` using mock DB session
- [x] 8.5 `tests/portfolio/test_snapshot.py` — `test_eod_snapshot_written_at_market_close()`: mock IST time to 15:36, assert MongoDB insert called with correct fields; `test_eod_snapshot_skipped_when_disabled()`

## 9. Validation

- [x] 9.1 Run `uv run ruff check src/pdp/portfolio/ tests/portfolio/` — zero errors
- [x] 9.2 Run `uv run pytest -x -q` — all tests pass
- [ ] 9.3 (Manual / live) Start with `LIVE=0`; place a paper order; call `GET /api/v1/portfolio/positions` and verify `unrealized_pnl` updates as ticks arrive; connect `/ws/portfolio` and verify push events
