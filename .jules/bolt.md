## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.

## 2024-06-20 - Redis Pipelining in Hot Paths
**Learning:** In high-frequency data paths like tick streaming, performing multiple sequential Redis operations (e.g., set, publish) results in unnecessary network round-trips that can block the event loop.
**Action:** Group sequential, independent Redis commands into an `async with redis.pipeline(transaction=False) as pipe:` block to execute them in a single network round-trip.
