## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.

## 2025-02-18 - Batch Redis commands in tick hot path
**Learning:** High-frequency paths like tick processing can suffer from multiple independent network roundtrips to Redis.
**Action:** Use `redis.pipeline(transaction=False)` to batch multiple non-dependent Redis commands (like setting LTP and publishing ticks) to reduce event loop contention and network overhead.
