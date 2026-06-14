# src/ — Python Source Root

**Package:** `pdp` (importable as `from pdp.xxx import ...`)
**Location:** `src/pdp/` — all application code lives here.
**Standard:** strict pyright + ruff. No bare `print()` — use `structlog`.

## Module map

| Module | Purpose |
|--------|---------|
| `main.py` | FastAPI app factory + lifespan wiring |
| `settings.py` | All env vars via `pydantic-settings` (`get_settings()`) |
| `logging.py` | structlog JSON setup |
| `cli.py` | Click CLI entry point (`python -m pdp`) |
| `alerts/` | Alert rules, evaluator, WebSocket hub |
| `backtest/` | BacktestEngine, sim, commissions, output |
| `cli/` | Click sub-commands (strategy, backtest, progress) |
| `db/` | SQLAlchemy base + async session factory |
| `indicators/` | IndicatorEngine, SuperTrend tracker, warmup |
| `instruments/` | Dhan scrip master loader, expiry calendar |
| `journal/` | Fill recording, daily stats (paper_journal) |
| `market/` | TickRouter, BarAggregator, WebSocket hub |
| `mongo/` | MongoDB client singleton + collection init |
| `options/` | OptionsChainPoller, Greeks, gap_backfill |
| `orders/` | PaperBroker, DhanBroker, OrderRouter |
| `portfolio/` | PortfolioService, MTM P&L, kill-switch |
| `positional/` | Swing F&O + equity position tracking |
| `risk/` | KillSwitchService, hard-cap auto-kill |
| `strategies/` | Concrete strategy implementations (Python) |
| `strategy/` | StrategyHost, BaseStrategy ABC, StrategyContext |
| `warehouse/` | Abi DuckDB → MongoDB migration pipeline |

## Key conventions

- Settings always via `get_settings()` — never `os.getenv()` in core modules
- Async SQLAlchemy sessions via `get_session()` (from `pdp.db.session`)
- MongoDB client via `get_mongo_client()` (from `pdp.mongo.client`)
- Response models: `msgspec.Struct` on hot paths, `pydantic` for input validation
