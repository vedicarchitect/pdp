# Strategy Module

## Files

| File | Size | Role |
|------|------|------|
| `host.py` | 13 KB | `StrategyHost` — loads YAML configs, subscribes to ticks/bars/fills, manages lifecycle |
| `context.py` | 10.8 KB | `StrategyContext` — passed to every strategy `on_bar()` call; holds order_router, indicators, positions |
| `abc.py` | 3.7 KB | `BaseStrategy` abstract class — implement `on_bar(ctx)` |
| `registry.py` | 3.2 KB | `load_all(dir)` → `list[StrategyConfig]` from YAML |
| `recovery.py` | 4 KB | Crash-recovery: restores open positions on restart |
| `log.py` | 1.5 KB | Strategy-specific structured logging helpers |
| `strikes.py` | 3.6 KB | Strike selection helpers (ATM, OTM ±N) |
| `schemas.py` | 0.8 KB | Pydantic schemas for strategy API |
| `routes.py` | 1.8 KB | `/strategy` endpoints (list, start, stop, status) |

## Strategy YAML Config (strategies/*.yaml)

```yaml
id: my_strategy
class: pdp.strategies.MyStrategy   # importable class path
watchlist:
  - security_id: "13"              # Dhan security ID
    exchange_segment: NSE_FNO
    timeframes: ["1m", "5m"]
risk:
  max_qty: 50
  stop_loss_pct: 0.5
```

See `strategies/example.yaml.tpl` for full schema. `StrategyHost` auto-loads all `*.yaml` from `./strategies/` on startup.

## Implementing a Strategy

```python
# src/pdp/strategies/my_strategy.py
from pdp.strategy.abc import BaseStrategy
from pdp.strategy.context import StrategyContext

class MyStrategy(BaseStrategy):
    async def on_bar(self, ctx: StrategyContext) -> None:
        st = ctx.indicators.supertrend   # never recompute — consume from engine
        if st.direction == 1:
            await ctx.buy(qty=25, order_type="MARKET")
```

## StrategyContext Key Attributes

```python
ctx.bar          # current closed bar (OHLCV)
ctx.security_id
ctx.timeframe
ctx.indicators   # IndicatorSnapshot (supertrend, etc.)
ctx.positions    # open positions for this strategy
ctx.order_router # place orders (paper or live based on settings)
ctx.settings     # full Settings object
ctx.session      # AsyncSession (PostgreSQL)
```

## Rules

- Strategies **consume** indicators from `ctx.indicators` — never compute inside `on_bar()`.
- Place orders only via `ctx.order_router` or `ctx.buy/sell` helpers.
- Crash recovery is automatic — `recovery.py` restores positions on `StrategyHost` restart.
- **Position isolation**: all `StrategyContext` position queries (`get_net_qty`, `get_position`, `get_realized_pnl`, `get_positions`) filter by `strategy_id`. Each strategy sees only its own rows — no cross-strategy bleed. Fixed 2026-06-18 via migration `0012`.
- Active specs: `live-supertrend-session-warmup`.
