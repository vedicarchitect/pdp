## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.

## 2024-06-16 - Pre-computing O(1) lookups in React render loops
**Learning:** Using `Array.prototype.find()` inside deeply nested React render loops (like rendering a matrix of data points) creates an O(N*M*K) performance bottleneck that causes significant rendering lag.
**Action:** Pre-compute an O(1) lookup structure (like a `Map` of `Map`s) wrapped in a `useMemo` hook before the render cycle, reducing the complexity and preventing UI stutter during updates.
