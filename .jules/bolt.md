## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.

## 2024-06-22 - Optimize nested array find in render loops
**Learning:** Using Array.prototype.find() inside nested render loops for large datasets (like heatmaps) creates O(N*M*K) performance bottlenecks.
**Action:** Pre-compute an O(1) lookup structure (like a Map) inside a useMemo hook before the render loop.
