from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, APIRouter
from app.dependencies import init_dialogue_manager, set_dialogue_manager
from app.database import init_database, close_database, get_db, check_db_connection
from app.common.config import get_settings

from app.admin.bots.routes import router as bots_router
from app.admin.entities.routes import router as entities_router
from app.admin.intents.routes import router as intents_router
from app.admin.train.routes import router as train_router
from app.admin.test.routes import router as test_router
from app.admin.integrations.routes import router as integrations_router
from app.admin.chatlogs.routes import router as chatlogs_router


from app.bot.channels.rest.routes import router as rest_router
from app.bot.channels.facebook.routes import router as facebook_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB and dialogue manager
    init_database(settings)
    await init_dialogue_manager()

    yield

    # Graceful shutdown: clear dialogue manager and close DB
    await set_dialogue_manager(None)
    close_database()


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
    """Readiness endpoint verifies DB connectivity and DM health"""
    db = get_db()
    ok = await check_db_connection(db)
    return {"status": "ok"} if ok else {"status": "unavailable"}


@app.get("/live")
async def live():
    """Liveness endpoint to indicate process is alive"""
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