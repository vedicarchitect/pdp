# PDP — Project Profile

## Mission

A self-hosted, **OpenSpec-driven** trading and investment platform covering:

- **Intraday**: algo + manual options/futures trading on NIFTY / BANKNIFTY / SENSEX
- **Positional**: swing F&O and equity positions with Greek/expiry awareness
- **Portfolio**: long-term equity & mutual-fund holdings, real-time P&L, corporate actions

Everything is spec-first: no implementation lands without a proposal under `openspec/changes/`.

## Tech Stack

| Layer            | Choice                                            |
|------------------|---------------------------------------------------|
| Language         | Python 3.13                                       |
| Package mgr      | `uv` (lock + sync)                                |
| Web framework    | FastAPI + uvicorn (uvloop, httptools)             |
| Response models  | `msgspec.Struct` (hot path), `pydantic` (input)   |
| DataFrame engine | Polars                                            |
| DB (cold)        | PostgreSQL 16 + TimescaleDB 2 (hypertables)       |
| DB (hot/cache)   | Redis 7 (pub/sub + streams + hash)                |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic                    |
| HTTP client      | httpx (async)                                     |
| Logging          | structlog (JSON to stdout)                        |
| Tests            | pytest + pytest-asyncio                           |
| Lint/format      | ruff                                              |
| Type check       | pyright (strict on `src/pdp/`)                    |
| Task runner      | Taskfile.yml                                      |
| Broker (v1)      | Dhan (paper + live-gated)                         |
| Frontend (later) | Vite + React 19 + TanStack Query + shadcn/ui      |

## Conventions

- **Paper-first**: orders route to the paper engine unless `LIVE=1` AND broker is wired.
- **Spec-first**: every capability lives under `openspec/specs/<capability>/spec.md` after archival.
- **One mutation per route**: avoid kitchen-sink endpoints.
- **Universal indicators**: levels/indicators/value-areas computed once, consumed by all strategies.
- **Latency budget**: tick → WebSocket fan-out p99 ≤ 50ms on a single instrument.
- **Settings via env** + `pydantic-settings`; never read `os.environ` directly in app code.
- **Structured logging only**: no bare `print()` or `rich` output inside core modules.

## Glossary

- **Tick** — single market quote from broker WS (LTP, volume, OI).
- **Bar** — time-bucketed OHLCV (1m/5m/15m/30m/1H).
- **Snapshot** — current indicator/level state for `(security_id, timeframe)`.
- **Capability** — a self-contained domain feature backed by one spec folder.
- **Change** — an in-flight proposal under `openspec/changes/<id>/`.

## Layout

```
PDP/
├── openspec/
│   ├── project.md          # this file
│   ├── changes/            # in-flight proposals
│   └── specs/              # archived capabilities (source of truth)
├── src/pdp/
│   ├── main.py             # FastAPI app factory
│   ├── settings.py
│   ├── logging.py
│   ├── db/                 # session + models
│   ├── market/             # feed, bars, indicators
│   ├── orders/             # paper + broker adapters
│   ├── portfolio/          # holdings, positions, P&L
│   ├── strategy/           # pluggable strategy host
│   └── api/                # routes
├── tests/
├── alembic/
├── docker-compose.yml
├── Taskfile.yml
└── pyproject.toml
```
