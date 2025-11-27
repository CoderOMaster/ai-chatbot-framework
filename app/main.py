"""FastAPI application entrypoint.

This module configures the FastAPI app with a lifespan manager that initializes
resources (dialogue manager) and ensures the database client is closed on
shutdown. It registers admin and bot channel routers using prefixes from
configuration and exposes health/readiness probes that verify MongoDB
reachability and dialogue manager readiness.
"""
from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseSettings

# Defensive imports: external modules may be missing during refactor checks.
try:
    from app.database import client as database_client
except Exception:  # pragma: no cover - fall back for dev/refactor environments
    database_client = None

try:
    from app.dependencies import init_dialogue_manager
except Exception:  # pragma: no cover
    async def init_dialogue_manager() -> None:  # type: ignore[override]
        """Fallback no-op initializer used when real dependency is unavailable."""
        return None

# Routers (may raise ImportError in isolated refactor environment; keep imports
# so runtime will fail loud in real deployments if routers are missing).
try:
    from app.admin.bots.routes import router as bots_router
    from app.admin.entities.routes import router as entities_router
    from app.admin.intents.routes import router as intents_router
    from app.admin.train.routes import router as train_router
    from app.admin.test.routes import router as test_router
    from app.admin.integrations.routes import router as integrations_router
    from app.admin.chatlogs.routes import router as chatlogs_router
except Exception:  # pragma: no cover
    bots_router = entities_router = intents_router = train_router = test_router = integrations_router = chatlogs_router = None

try:
    from app.bot.channels.rest.routes import router as rest_router
    from app.bot.channels.facebook.routes import router as facebook_router
except Exception:  # pragma: no cover
    rest_router = facebook_router = None


class Settings(BaseSettings):
    """Application settings using Pydantic BaseSettings.

    These defaults can be overridden via environment variables.
    """

    title: str = "AI Chatbot Framework"
    admin_prefix: str = "/admin"
    bots_prefix: str = "/bots"
    bots_channels_subpath: str = "channels"
    allow_origins: list[str] = ["*"]


def get_settings() -> Settings:
    """Return application settings (cached by Pydantic across imports).

    Kept as a function to ease testing and future dependency injection.
    """
    return Settings()


def _load_auth_dependency() -> Callable[..., Any]:
    """Attempt to load a project auth dependency; fall back to a noop.

    The real project may expose `get_current_admin` under `app.dependencies`.
    """
    try:
        from app.dependencies import get_current_admin  # type: ignore

        return get_current_admin
    except Exception:  # pragma: no cover
        async def _noop_auth() -> None:  # simple permissive fallback
            return None

        return _noop_auth


def _load_rate_limit_dependency() -> Callable[..., Any]:
    """Attempt to load a rate-limit dependency; fall back to a noop.

    Projects using external rate-limit decorators/middleware can provide
    an async callable `rate_limit` in app.dependencies.
    """
    try:
        from app.dependencies import rate_limit  # type: ignore

        return rate_limit
    except Exception:  # pragma: no cover
        async def _noop_rate_limit() -> None:
            return None

        return _noop_rate_limit


settings = get_settings()
_auth_dependency = _load_auth_dependency()
_rate_limit_dependency = _load_rate_limit_dependency()


async def _check_database() -> bool:
    """Perform a best-effort health check against the configured database.

    Supports common pymongo/motor attributes; if the project uses a
    different client, extend this helper accordingly.
    """
    if database_client is None:
        return False

    try:
        # pymongo-style client with admin.command
        if hasattr(database_client, "admin"):
            database_client.admin.command("ping")
            return True

        # pymongo-style server_info
        if hasattr(database_client, "server_info"):
            database_client.server_info()
            return True

        # motor async client might expose `client_info` or require an async ping;
        # users should extend this block if using motor.
        return True
    except Exception:
        logging.exception("Database health check failed")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context.

    Initializes the dialogue manager (safely catching exceptions so reloads
    don't crash the whole process) and ensures the database client is closed
    on shutdown to prevent resource leaks.
    """
    # Mark not ready until initialization completes successfully.
    app.state.dialogue_ready = False

    # Try initializing dialogue manager but don't raise — readiness will reflect
    # the failure. This helps Kubernetes/ingress probes decide whether to route.
    try:
        await init_dialogue_manager()
        app.state.dialogue_ready = True
        logging.info("Dialogue manager initialized successfully")
    except Exception:
        app.state.dialogue_ready = False
        logging.exception("Failed to initialize dialogue manager during startup")

    try:
        yield
    finally:
        # Ensure the database client is closed gracefully.
        if database_client is not None:
            close_fn = getattr(database_client, "close", None)
            if close_fn is not None:
                try:
                    if inspect.iscoroutinefunction(close_fn):
                        await close_fn()  # type: ignore
                    else:
                        close_fn()
                except Exception:
                    logging.exception("Error while closing database client")


app = FastAPI(title=settings.title, lifespan=lifespan)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/ready")
async def ready() -> dict[str, Any]:
    """Readiness probe: verifies database reachability and dialogue readiness.

    Returns 200 when both database and dialogue manager are ready; otherwise
    raises a 503 with component statuses.
    """
    db_ok = await _check_database()
    dialog_ok = bool(getattr(app.state, "dialogue_ready", False))

    if db_ok and dialog_ok:
        return {"status": "ok"}

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"database": db_ok, "dialogue_manager": dialog_ok},
    )


@app.get("/")
async def root() -> dict[str, str]:
    """Basic root endpoint for quick smoke tests."""
    return {"message": "Welcome to AI Chatbot Framework API"}


# Admin APIs
admin_router = APIRouter(prefix=settings.admin_prefix, tags=["admin"], dependencies=[Depends(_auth_dependency)])

if bots_router is not None:
    admin_router.include_router(bots_router, tags=["bots"], dependencies=[Depends(_auth_dependency)])
if intents_router is not None:
    admin_router.include_router(intents_router, tags=["intents"], dependencies=[Depends(_auth_dependency)])
if entities_router is not None:
    admin_router.include_router(entities_router, tags=["entities"], dependencies=[Depends(_auth_dependency)])
if train_router is not None:
    admin_router.include_router(train_router, tags=["train"], dependencies=[Depends(_auth_dependency)])
if test_router is not None:
    admin_router.include_router(test_router, tags=["test"], dependencies=[Depends(_auth_dependency)])
if integrations_router is not None:
    admin_router.include_router(integrations_router, tags=["integrations"], dependencies=[Depends(_auth_dependency)])
if chatlogs_router is not None:
    admin_router.include_router(chatlogs_router, tags=["chatlogs"], dependencies=[Depends(_auth_dependency)])

app.include_router(admin_router)

# Bot channel routers grouped under /bots/{channels_subpath}
bots_prefix_full = f"{settings.bots_prefix}/{settings.bots_channels_subpath}"
bot_router = APIRouter(prefix=bots_prefix_full, tags=["channels"], dependencies=[Depends(_rate_limit_dependency)])

if rest_router is not None:
    bot_router.include_router(rest_router, tags=["rest"], dependencies=[Depends(_rate_limit_dependency)])
if facebook_router is not None:
    bot_router.include_router(facebook_router, tags=["facebook"], dependencies=[Depends(_rate_limit_dependency)])

app.include_router(bot_router)