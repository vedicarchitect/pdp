# alembic/ — Database Migrations

SQLAlchemy schema migrations managed by Alembic.

## Files

| File | Purpose |
|------|---------|
| `env.py` | Alembic runtime config — reads `DATABASE_SYNC_URL` from settings |
| `script.py.mako` | Migration file template |
| `versions/` | Migration revision files (applied in order) |

## Common commands

```powershell
task db:migrate                   # apply all pending (alembic upgrade head)

uv run alembic current            # show applied revision
uv run alembic history            # show full history
uv run alembic upgrade head       # apply all
uv run alembic downgrade -1       # roll back one
uv run alembic revision --autogenerate -m "add my_table"   # new migration
```

## Note on alembic.ini

`alembic.ini` **must stay at the repo root** — Alembic resolves `script_location = alembic` relative to the CWD where the command is run. Moving it inside `alembic/` would require all commands to be run from inside that folder, breaking `task db:migrate`.

## Convention

- `sqlalchemy.url` is intentionally blank in `alembic.ini` — the URL is read dynamically from `DATABASE_SYNC_URL` env var inside `env.py`.
- Migrations must be idempotent (use `IF NOT EXISTS`, `IF EXISTS` guards).
