## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.

## 2024-06-21 - O(N*M*K) bottleneck in render loop
**Learning:** Repeatedly calling `Array.prototype.find()` inside nested render loops for large data arrays creates severe O(N*M*K) performance bottlenecks in React components (e.g., heatmaps).
**Action:** Always pre-compute O(1) lookup maps (e.g., using `useMemo` and `Map`) before rendering nested structures with cross-referenced data.
