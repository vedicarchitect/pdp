## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.

## 2026-07-01 - Batching Redis Commands on Tick Router
**Learning:** The tick router's `_handle` method is a hot path processing every tick. Doing multiple sequential `await redis.set` and `await redis.publish` calls adds significant network roundtrip latency.
**Action:** Use `redis.pipeline(transaction=False)` to batch independent Redis commands on the hot path to reduce network I/O overhead.
