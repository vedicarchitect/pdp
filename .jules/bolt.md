## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.

## 2024-07-03 - Batching High-Frequency Redis Operations
**Learning:** In high-frequency paths like tick processing, multiple contiguous asynchronous Redis calls (like `set` and `publish`) cause unnecessary network roundtrips, increasing latency.
**Action:** Use `redis.pipeline(transaction=False)` to batch these operations into a single network roundtrip, significantly improving throughput without sacrificing data consistency.
