## 2024-06-14 - Batching Redis network calls in high-frequency path
**Learning:** In a high-frequency market data path, making individual `await redis.set()` and `await redis.publish()` calls per tick causes significant latency due to multiple network roundtrips.
**Action:** Always use `redis.pipeline(transaction=False)` to batch multiple non-dependent Redis commands when processing high-frequency data like ticks.
