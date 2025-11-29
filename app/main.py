from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.admin.bots.routes import router as bots_router
from app.admin.chatlogs.routes import router as chatlogs_router
from app.admin.entities.routes import router as entities_router
from app.admin.integrations.routes import router as integrations_router
from app.admin.intents.routes import router as intents_router
from app.admin.test.routes import router as test_router
from app.admin.train.routes import router as train_router
from app.bot.channels.facebook.routes import router as facebook_router
from app.bot.channels.rest.routes import router as rest_router
from app.database import client as database_client
from app.dependencies import init_dialogue_manager


@asynccontextmanager
async def _bot_lifespan(_: FastAPI):
    await init_dialogue_manager()
    try:
        yield
    finally:
        database_client.close()


admin_app = FastAPI(title="AI Chatbot Framework Admin")

admin_router = APIRouter(prefix="/admin")
admin_router.include_router(bots_router)
admin_router.include_router(intents_router)
admin_router.include_router(entities_router)
admin_router.include_router(train_router)
admin_router.include_router(test_router)
admin_router.include_router(integrations_router)
admin_router.include_router(chatlogs_router)

admin_app.include_router(admin_router)


@admin_app.get("/ready")
async def admin_ready() -> dict[str, str]:
    """Return the readiness status for admin operations."""
    return {"status": "ok"}


@admin_app.get("/")
async def admin_root() -> dict[str, str]:
    """Describe the admin service entry point."""
    return {"message": "Admin APIs for AI Chatbot Framework"}


bot_app = FastAPI(title="AI Chatbot Framework", lifespan=_bot_lifespan)

bot_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot_app.mount("/static", StaticFiles(directory="app/static"), name="static")


@bot_app.get("/ready")
async def ready() -> dict[str, str]:
    """Return the readiness status for bot-facing operations."""
    return {"status": "ok"}


@bot_app.get("/")
async def root() -> dict[str, str]:
    """Describe the bot service entry point."""
    return {"message": "Welcome to AI Chatbot Framework API"}


bot_router = APIRouter(prefix="/bots/channels", tags=["channels"])
bot_router.include_router(rest_router, tags=["rest"])
bot_router.include_router(facebook_router, tags=["facebook"])

bot_app.include_router(bot_router)

app = bot_app


__all__ = ["admin_app", "bot_app", "app"]