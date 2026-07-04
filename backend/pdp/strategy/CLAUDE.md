# Strategy Module

## Files

| File | Size | Role |
|------|------|------|
| `host.py` | 13 KB | `StrategyHost` — loads YAML configs, subscribes to ticks/bars/fills, manages lifecycle |
| `context.py` | 10.8 KB | `StrategyContext` — passed to every strategy `on_bar()` call; holds order_router, indicators, positions |
| `abc.py` | 3.7 KB | `BaseStrategy` abstract class — implement `on_bar(ctx)` |
| `registry.py` | 3.2 KB | `load_all(dir)` → `list[StrategyConfig]` from YAML (live configs only) |
| `unified_registry.py` | — | `strategy-registry-unification` — canonical-id registry spanning live `strategies/*.yaml` **and** backtest `backtest/configs/*.yaml`; `StrategyEntry{id, kind, underlying, params_schema, defaults}`, `load_all()`, `register_strategy()`, `canonical_id(run_label, underlying)` (used by `backtest/store.py` + `backtest/paper_compare.py` for canonical run identity) |
| `recovery.py` | 4 KB | Crash-recovery: restores open positions on restart |
| `log.py` | 1.5 KB | Strategy-specific structured logging helpers |
| `strikes.py` | 3.6 KB | Strike selection helpers (ATM, OTM ±N) |
| `schemas.py` | 0.8 KB | Pydantic schemas for strategy API |
| `routes.py` | — | `/api/v1/strategies` endpoints: list (merges live host state + `unified_registry`, adds `params_schema`/`defaults`/`source`), `POST /register` (new strategy via registry), start, stop; plus strangle-console + levels routers |
| `promotion.py` | ~2 KB | `promote_run(run_id, strategy_id)` — PASS-gate promote: writes `strategies/<id>.yaml` + `backtest_promotions` audit doc in Mongo |

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
- Adding a new strategy/params without a code change: use `/strategy:add` (`.claude/skills/strategy-add/SKILL.md`) — registers via `POST /api/v1/strategies/register`, immediately visible in `GET /api/v1/strategies` and launchable as a backtest. See `openspec/specs/strategy-registry/spec.md`.
