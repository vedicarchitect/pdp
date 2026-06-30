## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.
## 2024-05-19 - Batching Redis commands in high-frequency data paths
**Learning:** Sequential Redis commands in the hot path (like processing market ticks) cause unnecessary network roundtrips, slowing down overall event loop execution.
**Action:** Use `redis.pipeline(transaction=False)` to batch non-dependent Redis commands (like setting cache keys and publishing updates) to reduce network latency.
