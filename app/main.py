from contextlib import asynccontextmanager
import logging
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, APIRouter, Depends, HTTPException

from app.common.database import get_db, ping_db
from app.common.config import Settings
from app.dependencies import init_dialogue_manager, get_dialogue_manager

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
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize dialogue manager and verify DB connectivity
    await init_dialogue_manager()
    try:
        db = await get_db(settings)
        await ping_db(db)
        logger.info("DB connectivity verified on startup")
    except Exception as exc:
        logger.exception("Database connectivity check failed during startup: %s", exc)
        # don't crash hard; rely on readiness endpoint to reflect status
    yield
    # Shutdown: allow dialogue manager to cleanup if it exposes close()
    dm = await get_dialogue_manager()
    if dm and hasattr(dm, "close"):
        try:
            await dm.close()  # type: ignore
            logger.info("Dialogue manager closed successfully")
        except Exception:  # pragma: no cover
            logger.exception("Failed to close dialogue manager cleanly")


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
    # Check DB and dialogue manager health
    try:
        db = await get_db(settings)
        await ping_db(db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"db not ready: {exc}")
    dm = await get_dialogue_manager()
    if dm is None:
        raise HTTPException(status_code=503, detail="dialogue manager not initialized")
    return {"status": "ok"}


@app.get("/live")
async def live():
    # liveness should be light-weight; if process is up return ok
    return {"status": "ok"}


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