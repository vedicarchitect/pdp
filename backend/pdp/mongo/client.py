from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from pdp.settings import Settings


def connect(settings: Settings) -> tuple[AsyncIOMotorClient, AsyncIOMotorDatabase]:  # type: ignore[type-arg]
    """Create a Motor client with bounded pool size and explicit timeouts.

    All four tunables come from Settings so they can be adjusted via env-vars
    without a code change:
    * MONGO_SOCKET_TIMEOUT_MS  — stalled operation raises instead of hanging
    * MONGO_CONNECT_TIMEOUT_MS — initial handshake timeout
    * MONGO_MAX_POOL_SIZE      — Motor connection pool ceiling
    * MONGO_MAX_IDLE_TIME_MS   — idle connection recycle threshold
    """
    client: AsyncIOMotorClient = AsyncIOMotorClient(  # type: ignore[type-arg]
        settings.MONGO_URI,
        socketTimeoutMS=settings.MONGO_SOCKET_TIMEOUT_MS,
        connectTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
        serverSelectionTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
        maxPoolSize=settings.MONGO_MAX_POOL_SIZE,
        maxIdleTimeMS=settings.MONGO_MAX_IDLE_TIME_MS,
    )
    db: AsyncIOMotorDatabase = client[settings.MONGO_DB_NAME]  # type: ignore[index]
    return client, db


def disconnect(client: AsyncIOMotorClient) -> None:  # type: ignore[type-arg]
    client.close()
