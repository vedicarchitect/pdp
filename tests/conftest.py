from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://pdp:pdp@localhost:5432/pdp"
)
os.environ.setdefault(
    "DATABASE_SYNC_URL", "postgresql+psycopg://pdp:pdp@localhost:5432/pdp"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
