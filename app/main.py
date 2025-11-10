from contextlib import asynccontextmanager
import logging
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, APIRouter, Depends, HTTPException

from ai_chatbot_common.config import get_settings
from ai_chatbot_common.database import wait_for_db, get_db

# Dialogue manager lifecycle via DI (externalized construction)
from app.dependencies import get_dialogue_manager, init_dialogue_manager

from app.admin.bots.routes import router as bots_router
from app.admin.entities.routes import router as entities_router
from app.admin.intents.routes import router as intents_router
from app.admin.train.routes import router as train_router
from app.admin.test.routes import router as test_router
from app.admin.integrations.routes import router as integrations_router
from app.admin.chatlogs.routes import router as chatlogs_router

from app.bot.channels.rest.routes import router as rest_router
from app.bot.channels.facebook.routes import router as facebook_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("[startup] initializing core-api with settings: %s", settings.dict() if hasattr(settings, 'dict') else 'loaded')
    # Initialize dialogue manager (now DI-friendly)
    await init_dialogue_manager()

    # Ensure DB is reachable (creates pool under the hood via Motor)
    try:
        await wait_for_db()
        logger.info("[startup] database connectivity OK")
    except Exception as exc:
        logger.exception("[startup] database connectivity failed: %s", exc)
        # Do not crash startup in dev; production should still fail healthchecks
    try:
        yield
    finally:
        # Motor client is managed by lru_cache in common.database; nothing explicit here
        logger.info("[shutdown] core-api shutting down gracefully")


app = FastAPI(title="AI Chatbot Framework", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/ready")
async def ready():
    # Check DB and dialogue manager readiness
    try:
        await wait_for_db(max_retries=1, delay_seconds=0.1)
    except Exception:
        raise HTTPException(status_code=503, detail="database not ready")

    dm = await get_dialogue_manager()
    if dm is None:
        raise HTTPException(status_code=503, detail="dialogue manager not ready")
    return {"status": "ok"}


@app.get("/live")
async def live():
    # Liveness should be cheap and not depend on external systems
    return {"status": "alive"}


@app.get("/")
async def root():
    return {"message": "Welcome to AI Chatbot Framework API"}


# admin apis
admin_router = APIRouter(prefix="/admin")
admin_router.include_router(bots_router)
admin_router.include_router(intents_router)
admin_router.include_router(entities_router)
admin_router.include_router(train_router)
admin_router.include_router(test_router)
admin_router.include_router(integrations_router)
admin_router.include_router(chatlogs_router)


app.include_router(admin_router)

bot_router = APIRouter(prefix="/bots/channels", tags=["channels"])
bot_router.include_router(rest_router, tags=["rest"])
bot_router.include_router(facebook_router, tags=["facebook"])


app.include_router(bot_router)