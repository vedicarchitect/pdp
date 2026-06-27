from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from pdp.settings import Settings


def connect(settings: Settings) -> tuple[AsyncIOMotorClient, AsyncIOMotorDatabase]:  # type: ignore[type-arg]
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=2000)  # type: ignore[type-arg]
    db: AsyncIOMotorDatabase = client[settings.MONGO_DB_NAME]  # type: ignore[index]
    return client, db


def disconnect(client: AsyncIOMotorClient) -> None:  # type: ignore[type-arg]
    client.close()
