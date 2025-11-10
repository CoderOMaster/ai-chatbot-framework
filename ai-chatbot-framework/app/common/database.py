from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import AsyncGenerator, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from ai_chatbot_common.config import get_settings


DEFAULT_CONNECT_TIMEOUT_MS = 10000
DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 10000
DEFAULT_SOCKET_TIMEOUT_MS = 10000
DEFAULT_MAX_POOL_SIZE = 100


def _mongo_uri_from_env() -> str:
    settings = get_settings()
    host = settings.MONGODB_HOST
    return host


@lru_cache(maxsize=1)
def get_mongo_client() -> AsyncIOMotorClient:
    uri = _mongo_uri_from_env()
    max_pool_size = int(os.getenv("MONGODB_MAX_POOL_SIZE", str(DEFAULT_MAX_POOL_SIZE)))
    connect_timeout_ms = int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", str(DEFAULT_CONNECT_TIMEOUT_MS)))
    server_selection_timeout_ms = int(
        os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", str(DEFAULT_SERVER_SELECTION_TIMEOUT_MS))
    )
    socket_timeout_ms = int(os.getenv("MONGODB_SOCKET_TIMEOUT_MS", str(DEFAULT_SOCKET_TIMEOUT_MS)))

    client = AsyncIOMotorClient(
        uri,
        maxPoolSize=max_pool_size,
        connectTimeoutMS=connect_timeout_ms,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
        socketTimeoutMS=socket_timeout_ms,
        retryWrites=True,
        uuidRepresentation="standard",
    )
    return client


def get_db() -> AsyncIOMotorDatabase:
    settings = get_settings()
    client = get_mongo_client()
    return client.get_database(settings.MONGODB_DATABASE)


async def wait_for_db(max_retries: int = 5, delay_seconds: float = 0.5) -> None:
    """Simple retry/backoff health check. Raises on failure after retries."""
    retries = 0
    last_exc: Optional[Exception] = None
    while retries < max_retries:
        try:
            db = get_db()
            # Ping the server
            await db.command("ping")
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            await asyncio.sleep(delay_seconds * (2 ** retries))
            retries += 1
    if last_exc:
        raise last_exc


# FastAPI dependency helper (sync function returning db works for Motor)
async def db_dependency() -> AsyncGenerator[AsyncIOMotorDatabase, None]:
    db = get_db()
    yield db