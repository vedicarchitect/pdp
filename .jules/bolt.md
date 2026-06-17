## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.
## 2026-06-17 - Deferring JSON Serialization in WebSocket Broadcasts
**Learning:** In high-frequency market data systems, eagerly serializing data to JSON for every tick/event (before checking if any clients are subscribed) is a major CPU bottleneck and blocks the main thread.
**Action:** Always filter for subscribed clients first, and only serialize the payload (`json.dumps()`) if the target list is not empty.
