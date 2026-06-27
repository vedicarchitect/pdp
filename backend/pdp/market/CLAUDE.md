# Market Feed Module

## Files

| File | Size | Role |
|------|------|------|
| `dhan_ws.py` | 11.2 KB | `DhanTickerAdapter` — WS client to Dhan feed; produces tick queue; only starts if creds set |
| `router.py` | 5.9 KB | `TickRouter.run(queue, redis)` — hot path; fan-out tick to bar/WS/strategy/alerts |
| `bars.py` | 4.9 KB | `BarAggregator` — buckets ticks into 1m/5m/15m/30m/1H OHLCV bars |
| `bar_writer.py` | 3.1 KB | `BarWriter` — async batch writer to MongoDB `market_bars` collection |
| `ws.py` | 4.8 KB | `WSHub` + `ws_router` — `/ws/market` endpoint; streams ticks to browser |
| `routes.py` | 3.6 KB | REST: subscribe/unsubscribe instruments, get latest bars |
| `subscription_model.py` | 0.7 KB | `Subscription` dataclass |
| `models.py` | 0.4 KB | `Bar` dataclass |

## Hot Path (latency budget: p99 ≤ 50ms)

```
DhanTickerAdapter.queue
  → TickRouter.run()
      ├── Redis SET ltp:<security_id> EX5       # LTP cache for PaperBroker
      ├── Redis PUBLISH tick.<security_id>       # pub/sub
      ├── WSHub.broadcast(tick)                 # → browser clients
      ├── BarAggregator.on_tick(tick)
      │     on bar close:
      │       ├── Redis XADD bars.<id>.<tf>
      │       ├── BarWriter.enqueue(bar)  →  MongoDB market_bars
      │       ├── IndicatorEngine.update(bar)
      │       └── StrategyHost.on_bar(bar)
      └── AlertEvaluator.on_tick(tick)
```

## Rules

- **No blocking calls in TickRouter.run()** — everything must be `asyncio`-native or offloaded.
- Bar timeframes are computed by `BarAggregator`; don't hardcode timeframe logic elsewhere.
- `DhanTickerAdapter` only starts when `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` are set.

## MongoDB `market_bars` Schema

```python
{
  "security_id": str,
  "exchange_segment": str,
  "timeframe": str,         # "1m", "5m", etc.
  "ts": datetime,           # bar open timestamp (UTC)
  "open": Decimal,
  "high": Decimal,
  "low": Decimal,
  "close": Decimal,
  "volume": int,
  "oi": int | None
}
```

Indexes: `(security_id, timeframe, ts)` unique. TTL controlled by `MONGO_CHAIN_TTL_DAYS`.
