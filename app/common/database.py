from __future__ import annotations

from typing import Optional, Tuple, List
from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ai_chatbot_common.config import get_settings, Settings

# Track created clients so we can close them on shutdown
_clients: List[AsyncIOMotorClient] = []


def _register_client(c: AsyncIOMotorClient) -> AsyncIOMotorClient:
    try:
        _clients.append(c)
    except Exception:
        pass
    return c


def _client_cache_key(settings: Settings) -> Tuple[str, int, int, int]:
    """Compute a cache key for the Mongo client based on effective connection params.

    We avoid caching on the Settings object itself since it is not hashable.
    """
    return (
        settings.MONGODB_HOST,
        int(getattr(settings, "MONGODB_MAX_POOL_SIZE", 100) or 100),
        int(getattr(settings, "MONGODB_CONNECT_TIMEOUT_MS", 2000) or 2000),
        int(getattr(settings, "MONGODB_SERVER_SELECTION_TIMEOUT_MS", 2000) or 2000),
    )


@lru_cache(maxsize=4)
def _build_client_cached(host: str, max_pool: int, connect_timeout_ms: int, server_selection_timeout_ms: int) -> AsyncIOMotorClient:
    """Instantiate the motor client with optional tuning.

    Falls back to minimal constructor if the target class does not accept kwargs
    (useful in tests that monkeypatch AsyncIOMotorClient).
    """
    try:
        client = AsyncIOMotorClient(
            host,
            maxPoolSize=max_pool,
            connectTimeoutMS=connect_timeout_ms,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
        )
    except TypeError:
        # Dummy or test client without kwargs support
        client = AsyncIOMotorClient(host)
    return _register_client(client)


def get_mongo_client(settings: Optional[Settings] = None) -> AsyncIOMotorClient:
    """Create or return a cached AsyncIOMotorClient based on Settings.

    The client is cached per unique tuple of (host, pool size, timeouts).
    """
    s = settings or get_settings()
    host = s.MONGODB_HOST
    max_pool = int(getattr(s, "MONGODB_MAX_POOL_SIZE", 100) or 100)
    connect_timeout_ms = int(getattr(s, "MONGODB_CONNECT_TIMEOUT_MS", 2000) or 2000)
    server_selection_timeout_ms = int(getattr(s, "MONGODB_SERVER_SELECTION_TIMEOUT_MS", 2000) or 2000)
    # Use our small cache keyed on the connection params
    return _build_client_cached(host, max_pool, connect_timeout_ms, server_selection_timeout_ms)


def close_mongo_client() -> None:
    """Close any created client instances and clear caches.

    Useful on application shutdown hooks.
    """
    try:
        for c in list(_clients):
            try:
                c.close()
            except Exception:
                pass
        _clients.clear()
    finally:
        _build_client_cached.cache_clear()


async def get_db() -> AsyncIOMotorDatabase:
    """FastAPI-friendly dependency that returns the configured database instance."""
    s = get_settings()
    client = get_mongo_client(s)
    return client.get_database(s.MONGODB_DATABASE)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
    retry=retry_if_exception_type((ServerSelectionTimeoutError, PyMongoError)),
    reraise=True,
)
async def check_db_health(timeout_ms: Optional[int] = None) -> bool:
    """Ping the MongoDB server to verify connectivity.

    Returns True if healthy, raises on failure. Retries are applied with exponential backoff.
    """
    s = get_settings()
    db = await get_db()
    await db.command({"ping": 1})
    if getattr(s, "MONGODB_HEALTHCHECK_ENABLED", True):
        return True
    return True