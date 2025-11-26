"""Application entrypoints split into admin and bot ASGI apps.

This module creates two FastAPI instances:
- admin_app: a lightweight proxy that forwards admin requests to an external
  Admin API (API Gateway / Lambdas). It intentionally does not initialize the
  heavyweight in-process dialogue manager.
- bot_app: the bot-facing application that mounts the REST and Facebook
  channel routers and initializes the dialogue manager at startup.

For backwards compatibility the module-level name `app` points to bot_app so
existing deployment commands (uvicorn app.main:app) continue to work while the
project migrates admin endpoints to separate services.
"""
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
import os

import aiohttp
from fastapi import FastAPI, APIRouter, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import client as database_client
from app.dependencies import init_dialogue_manager

# Bot-facing channel routers (kept here as this file will remain the bot
# microservice). Admin routers are intentionally NOT imported to avoid
# coupling the bot service to admin implementations.
from app.bot.channels.rest.routes import router as rest_router
from app.bot.channels.facebook.routes import router as facebook_router


# ----------------
# Bot application
# ----------------

@asynccontextmanager
async def bot_lifespan(_: Any) -> AsyncGenerator[None, None]:
    """Lifespan for the bot-facing service.

    Initializes the in-process dialogue manager (monolith or dedicated
    dialogue-manager container) and ensures database client is closed on
    shutdown. This should only be used when running the dialogue-manager
    in this container; admin-only deployments should not use this startup
    hook.
    """
    await init_dialogue_manager()
    try:
        yield
    finally:
        # Keep using the existing database client shutdown for now; the
        # database should be accessed behind repositories in future refactors.
        try:
            database_client.close()
        except Exception:
            # Best-effort close; do not raise during shutdown
            pass


bot_app = FastAPI(title="AI Chatbot Framework - Bot", lifespan=bot_lifespan)

# CORS for bot endpoints
bot_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files served from the bot app
bot_app.mount("/static", StaticFiles(directory="app/static"), name="static")


@bot_app.get("/ready")
async def ready() -> dict:
    """Health check endpoint for the bot service."""
    return {"status": "ok"}


@bot_app.get("/")
async def root() -> dict:
    """Root welcome endpoint for the bot service."""
    return {"message": "Welcome to AI Chatbot Framework API (bot)"}


# Include bot channel routers under /bots/channels
bot_router = APIRouter(prefix="/bots/channels", tags=["channels"])
bot_router.include_router(rest_router, tags=["rest"])
bot_router.include_router(facebook_router, tags=["facebook"])

bot_app.include_router(bot_router)


# -----------------
# Admin application
# -----------------

admin_app = FastAPI(title="AI Chatbot Framework - Admin")

# Keep a permissive CORS policy on the admin proxy as well
admin_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@admin_app.get("/ready")
async def admin_ready() -> dict:
    """Health check for the admin proxy app."""
    return {"status": "ok"}


@admin_app.get("/")
async def admin_root() -> dict:
    """Minimal root for the admin proxy."""
    return {"message": "Admin API proxy"}


async def _proxy_to_admin_gateway(request: Request, path: str) -> Response:
    """Forward the incoming request to the configured Admin API gateway.

    This is a simple generic proxy used while admin routes are migrated to
    API Gateway / Lambdas. It forwards method, headers and body and returns
    the proxied response. The target base URL is read from the
    ADMIN_API_GATEWAY_URL environment variable.
    """
    admin_gateway = os.getenv("ADMIN_API_GATEWAY_URL")
    if not admin_gateway:
        return Response(content=b"Admin gateway not configured", status_code=502)

    # Build target URL
    query = request.url.query
    target = f"{admin_gateway.rstrip('/')}/{path.lstrip('/')}"
    if query:
        target = f"{target}?{query}"

    # Prepare headers to forward (remove hop-by-hop / host)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}

    body = await request.body()

    async with aiohttp.ClientSession() as session:
        async with session.request(request.method, target, data=body or None, headers=headers) as resp:
            content = await resp.read()
            # Choose a minimal set of headers to forward back
            response_headers = {}
            if "content-type" in resp.headers:
                response_headers["content-type"] = resp.headers["content-type"]
            return Response(content=content, status_code=resp.status, headers=response_headers)


# Generic catch-all that forwards admin API calls to the external gateway.
@admin_app.api_route("/admin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])  # type: ignore[misc]
async def admin_proxy(path: str, request: Request) -> Response:  # pragma: no cover - thin proxy
    return await _proxy_to_admin_gateway(request, path)


# For backwards compatibility deployments expect `app` to be the main ASGI
# application. Keep that name pointing to the bot app so existing startup
# commands continue to work until deployments are updated to reference
# bot_app or admin_app explicitly.
app: FastAPI = bot_app


__all__ = ["app", "bot_app", "admin_app"]