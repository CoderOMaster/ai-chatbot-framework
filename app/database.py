from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_app_config

logger = logging.getLogger(__name__)


async def create_mongo_client(
    config: Optional[Any] = None,
    uri: Optional[str] = None,
    max_retries: int = 3,
    initial_backoff: float = 0.5,
    max_backoff: float = 5.0,
    tls: Optional[bool] = None,
    tls_ca_file: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    auth_source: Optional[str] = None,
    **client_kwargs: Any,
) -> AsyncIOMotorClient:
    """Create an AsyncIOMotorClient with optional retry/backoff and TLS/auth support.

    Parameters
    - config: optional config object (produced by app.config.get_app_config()). If
      not provided, the function will call get_app_config() lazily.
    - uri: optional MongoDB URI. If provided it takes precedence over config host.
    - max_retries: number of attempts to verify connectivity (ping) before raising.
    - initial_backoff: initial backoff seconds between retries (exponential).
    - max_backoff: maximum backoff seconds.
    - tls, tls_ca_file, username, password, auth_source: optional connection options
      that will be passed to AsyncIOMotorClient or used to build the URI.
    - client_kwargs: additional keyword args forwarded to AsyncIOMotorClient.

    Returns
    - an instance of AsyncIOMotorClient which has passed an initial ping check.

    Notes
    - This factory avoids reading configuration at module import time to simplify
      testing and support dependency injection.
    """
    if config is None:
        # Lazily load app config to avoid heavy imports at module import time
        config = get_app_config()

    # Build URI if not provided
    if not uri:
        host = getattr(config, "MONGODB_HOST", None)
        if not host:
            raise ValueError("MONGODB_HOST must be set in configuration or a uri must be provided")

        # If auth info provided, prefer building a URI with credentials
        if username and password:
            uri = f"mongodb://{username}:{password}@{host}"
            if auth_source:
                uri += f"/?authSource={auth_source}"
        else:
            uri = f"mongodb://{host}"

    # If tls flag not explicitly passed, try to read from config
    if tls is None:
        tls = bool(getattr(config, "MONGODB_TLS", False))
    if tls_ca_file is None:
        tls_ca_file = getattr(config, "MONGODB_TLS_CA_FILE", None)

    attempt = 0
    backoff = initial_backoff
    last_exc: Optional[Exception] = None

    while attempt < max_retries:
        attempt += 1
        client: Optional[AsyncIOMotorClient] = None
        try:
            client = AsyncIOMotorClient(uri, tls=tls, tlsCAFile=tls_ca_file, username=username, password=password, authSource=auth_source, **client_kwargs)

            # Perform a lightweight connectivity check
            await client.admin.command("ping")
            logger.debug("MongoDB client connected on attempt %d", attempt)
            return client
        except Exception as exc:  # pragma: no cover - network errors are environment-specific
            last_exc = exc
            logger.warning("MongoDB connection attempt %d/%d failed: %s", attempt, max_retries, exc)
            # Close the client to free resources before retrying
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass

            if attempt >= max_retries:
                break

            # Exponential backoff with jitter
            jitter = random.uniform(-0.05 * backoff, 0.05 * backoff)
            sleep_for = min(max_backoff, backoff) + jitter
            await asyncio.sleep(max(0.0, sleep_for))
            backoff = min(max_backoff, backoff * 2)

    # If we get here, all retries failed
    logger.error("Failed to create MongoDB client after %d attempts", max_retries)
    raise last_exc if last_exc is not None else RuntimeError("Failed to create MongoDB client")


def get_database(client: AsyncIOMotorClient, db_name: Optional[str] = None, config: Optional[Any] = None) -> AsyncIOMotorDatabase:
    """Return a Database instance from a client.

    The function avoids reading configuration at import time and will lazily
    resolve the database name from the provided config if not specified.
    """
    if db_name is None:
        if config is None:
            config = get_app_config()
        db_name = getattr(config, "MONGODB_DATABASE")

    return client.get_database(db_name)


async def health_check(client: AsyncIOMotorClient) -> Dict[str, Any]:
    """Run a health check against the given AsyncIOMotorClient.

    Returns a dict containing a basic ping result and best-effort connection pool
    metrics when available.
    """
    result: Dict[str, Any] = {"connected": False}
    try:
        await client.admin.command("ping")
        result["connected"] = True
    except Exception as exc:  # pragma: no cover - depends on runtime MongoDB availability
        result["error"] = str(exc)

    pool_stats = _extract_pool_stats(client)
    if pool_stats is not None:
        result["pool"] = pool_stats

    return result


def _extract_pool_stats(client: AsyncIOMotorClient) -> Optional[Dict[str, Any]]:
    """Attempt to extract connection pool metrics from the underlying PyMongo client.

    This is a best-effort extractor that inspects internal attributes. Different
    PyMongo versions expose pool internals differently; callers should treat the
    returned information as implementation-detail and optional.
    """
    try:
        # Motor wraps a sync PyMongo MongoClient. Try to access it safely.
        pymongo_client = getattr(client, "delegate", None) or getattr(client, "_client", None) or client

        # Topology object may be available under different names
        topology = getattr(pymongo_client, "topology", None) or getattr(pymongo_client, "_topology", None)
        if not topology:
            return None

        # Servers mapping differs between versions; try common shapes
        servers = getattr(topology, "servers", None) or getattr(topology, "_servers", None) or {}
        pools = []
        if isinstance(servers, dict):
            iterable = servers.values()
        else:
            iterable = servers

        for server in iterable:
            try:
                pool = getattr(server, "pool", None)
                if not pool:
                    continue

                stats: Dict[str, Any] = {
                    "address": getattr(server, "address", None),
                    "in_use": getattr(pool, "sockets_in_use", None) or getattr(pool, "in_use", None),
                    "available": getattr(pool, "sockets_available", None) or getattr(pool, "available", None),
                    "created": getattr(pool, "total_created", None),
                }
                pools.append(stats)
            except Exception:
                continue

        return {"pools": pools} if pools else None
    except Exception:
        return None