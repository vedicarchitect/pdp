## Why

The live `WarehouseService` subscribes only to NIFTY option bars (`INDEX_SID = "13"`). To support live directional-strangle strategies on BANKNIFTY or SENSEX — or to maintain a real-time option bar warehouse for multiple indices — the service must be able to subscribe to multiple underlyings simultaneously. The current code is hardcoded at three levels: the security ID (`INDEX_SID = "13"`), the strike step (`STEP = 50`), and the underlying name (`_UNDERLYING = "NIFTY"`).

## What Changes

- **`src/pdp/settings.py`** — add `WAREHOUSE_UNDERLYINGS: list[str]` (default `["NIFTY"]`). Per-underlying static config (sid, step, expiry calendar path) resolved from a `WAREHOUSE_UNDERLYING_CONFIG` registry (not dynamic settings — only a small fixed set of supported underlyings).
- **`src/pdp/warehouse/writer.py`** — remove the module-level `INDEX_SID` constant (moves to per-instance config). `OptionBarWriter` accepts an `underlying_cfg` dict so writes are tagged correctly per symbol.
- **`src/pdp/warehouse/service.py`** — `WarehouseService` iterates over `WAREHOUSE_UNDERLYINGS`, instantiates one subscription band per underlying, and multiplexes incoming ticks to the correct writer by `security_id`. One Dhan WS connection continues to handle all subscriptions (Dhan WS accepts multiple security IDs per subscribe call).
- **`src/pdp/warehouse/service.py`** — the self-healing gap-backfill loop calls `gap_backfill.backfill_gaps()` with the per-underlying config (after `multi-index-options-backfill` lands; this change has a soft dep on that one for BANKNIFTY/SENSEX gap-heal).
- **Tests** — `tests/test_warehouse_feed.py` updated; `INDEX_SID` import removed (replaced by per-test underlying config fixture).

## Capabilities

### Modified Capabilities
- `options-warehouse`: live ingestion now covers configurable underlyings; default config (`WAREHOUSE_UNDERLYINGS=["NIFTY"]`) is identical to current behaviour.

### Out of Scope
- Historical backfill of BANKNIFTY/SENSEX option bars (covered by `multi-index-options-backfill`)
- BANKNIFTY/SENSEX strangle live strategy deployment (follows once warehouse is proven)
- Expiry calendar for BANKNIFTY/SENSEX (shared dep with `multi-index-options-backfill`)

## Impact

- Modify `src/pdp/settings.py` (`WAREHOUSE_UNDERLYINGS` list setting)
- Modify `src/pdp/warehouse/writer.py` (remove module-level `INDEX_SID`; per-instance config)
- Modify `src/pdp/warehouse/service.py` (multi-underlying subscription loop)
- Modify `src/pdp/warehouse/service.py` (gap-heal loop: per-underlying params)
- Modify `tests/test_warehouse_feed.py` (no more `INDEX_SID` import)
- Modify `src/pdp/warehouse/CLAUDE.md` (settings table, data-flow diagram)
- Modify `src/pdp/housekeeping/tasks.py` if any housekeeping task references `INDEX_SID`
- Soft dependency: `multi-index-options-backfill` (for gap-heal to work on BANKNIFTY/SENSEX)
- No new external dependencies; no new database tables or indexes
