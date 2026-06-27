# PDP — Backend (Python)

The FastAPI backend, strategies, backtests, migrations and data scripts for PDP.
This is the package root (`pdp`, imported as `pdp.*`); run all Python tooling from here
(`uv run ...`) or via the root `Taskfile.yml` (which sets `dir: backend`).

- App factory: `pdp/main.py`
- Settings: `pdp/settings.py`
- Migrations: `alembic/` (`alembic.ini` here)
- Backtests: `backtest/`  ·  Strategies: `strategies/`  ·  Ops scripts: `scripts/`
- Dev-activity context map: [`CLAUDE.md`](CLAUDE.md)

See the repo root [`README.md`](../README.md) and [`docs/`](../docs/) for the full picture.
