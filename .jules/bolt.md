## 2024-06-13 - Batching High-Frequency WebSocket Broadcasts
**Learning:** In high-frequency market data processing, synchronous websocket broadcasts triggered on every tick can severely block the asyncio event loop and cause CPU spikes due to repetitive JSON serialization of unchanged/rapidly changing state.
**Action:** When handling tick streams or similarly rapid events, use a dirty flag (`_needs_broadcast = True`) to debounce updates and defer the actual heavy lifting (serialization and broadcasting) to an existing periodic flush loop (e.g., a 100ms ticker). Always clear the dirty flag *before* beginning the heavy work to prevent losing subsequent updates.

## 2026-07-07 - Lazy JSON Serialization in High-Frequency WebSockets
**Learning:** Eagerly serializing JSON payloads for WebSocket broadcasting before checking if any clients are actually subscribed to that specific event (e.g. security_id) wastes significant CPU cycles in high-frequency data paths, as the payload is often discarded.
**Action:** Delay `json.dumps()` in high-frequency broadcast hubs until it is confirmed that at least one connected client matches the filtering criteria.
