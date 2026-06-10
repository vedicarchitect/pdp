## 2026-06-10 - O(N) Array Aggregation Optimization
**Learning:** For high-frequency ticking data (e.g., live market or portfolio feeds), repeatedly iterating over lists using multiple `reduce` passes causes significant CPU and garbage collection overhead, particularly when recalculating metrics (Greeks, P&L) on every WebSocket tick.
**Action:** Always combine aggregations into a single O(N) pass. In addition, when populating Maps, check for existence and create the array reference first instead of defaulting via `??` on every iteration, which eliminates redundant `map.set()` calls.
