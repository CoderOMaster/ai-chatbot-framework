from __future__ import annotations
import asyncio
from typing import Optional, AsyncGenerator
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import BaseModel
from .config import Settings

class MongoSettings(BaseModel):
    uri: Optional[str] = None
    host: str = "mongodb://localhost:27017"
    database: str = "chatbot"
    max_pool_size: int = 100
    server_selection_timeout_ms: int = 5000
    connect_timeout_ms: int = 5000
    socket_timeout_ms: int = 10000


def _build_mongo_uri(settings: Settings) -> str:
    # Prefer full URI if provided via MONGODB_HOST (compat) or MONGODB_URI
    host = getattr(settings, "MONGODB_HOST", None) or "mongodb://localhost:27017"
    return host

_client_singleton: Optional[AsyncIOMotorClient] = None


def get_mongo_client(settings: Optional[Settings] = None) -> AsyncIOMotorClient:
    global _client_singleton
    if _client_singleton:
        return _client_singleton
    settings = settings or Settings()
    uri = _build_mongo_uri(settings)
    max_pool = int(getattr(settings, "MONGODB_MAX_POOL_SIZE", 100))
    server_sel = int(getattr(settings, "MONGODB_SERVER_SELECTION_TIMEOUT_MS", 5000))
    connect_to = int(getattr(settings, "MONGODB_CONNECT_TIMEOUT_MS", 5000))
    socket_to = int(getattr(settings, "MONGODB_SOCKET_TIMEOUT_MS", 10000))

    _client_singleton = AsyncIOMotorClient(
        uri,
        maxPoolSize=max_pool,
        serverSelectionTimeoutMS=server_sel,
        connectTimeoutMS=connect_to,
        socketTimeoutMS=socket_to,
    )
    return _client_singleton


async def get_db(settings: Optional[Settings] = None) -> AsyncIOMotorDatabase:
    settings = settings or Settings()
    client = get_mongo_client(settings)
    return client.get_database(settings.MONGODB_DATABASE)


async def ping_db(settings: Optional[Settings] = None, timeout_s: float = 2.0, retries: int = 3) -> bool:
    settings = settings or Settings()
    client = get_mongo_client(settings)
    for attempt in range(retries):
        try:
            await client.admin.command("ping")
            return True
        except Exception:
            if attempt == retries - 1:
                return False
            await asyncio.sleep(min(0.5 * (2 ** attempt), timeout_s))
    return False