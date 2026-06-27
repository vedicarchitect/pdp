# db/ — SQLAlchemy Database Layer

PostgreSQL 16 — ACID ledger for orders, trades, positions, instruments, alerts.

## Files

| File | Purpose |
|------|---------|
| `base.py` | `DeclarativeBase` — all ORM models inherit from this |
| `session.py` | `AsyncSessionFactory`, `get_session()` FastAPI dependency |

## Usage

```python
from pdp.db.session import get_session
from sqlalchemy.ext.asyncio import AsyncSession

async def my_route(session: AsyncSession = Depends(get_session)):
    ...
```

## Drivers

- Async (app): `postgresql+asyncpg` — set in `DATABASE_URL`
- Sync (alembic): `postgresql+psycopg` — set in `DATABASE_SYNC_URL`

## Migration

Alembic managed — see `alembic/` at repo root.
```powershell
task db:migrate          # apply head
uv run alembic revision --autogenerate -m "my change"
uv run alembic downgrade -1
```

> `alembic.ini` must stay at the **repo root** — Alembic requires it at the directory where you run the command.
