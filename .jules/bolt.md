## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.
## 2024-06-24 - Pre-compute O(1) lookup in OIHeatmap render loop
**Learning:** In React components rendering large nested datasets (e.g., heatmaps or charts), using `Array.prototype.find()` inside render loops creates O(N*M*K) performance bottlenecks. Pre-computing O(1) lookup structures (e.g., using `Map` within `useMemo`) prevents blocking the main thread.
**Action:** Use pre-computed `Map` lookups inside `useMemo` instead of `Array.prototype.find()` in render loops.
