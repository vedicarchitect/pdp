## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.
## 2026-07-04 - O(1) Tick Lookups
**Learning:** High-frequency tick handlers shouldn't iterate over O(n) caches when they only need to update specific items by an identifier. In high-frequency market data processing (like Redis tick streams), O(n) loops inside event handlers can block the asyncio event loop and cause CPU spikes.
**Action:** Pre-compute secondary index dictionaries mapping specific identifiers (like security IDs) to main cache keys to enable O(1) lookups inside tick handlers.
