from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, APIRouter
from app.common.database import close_mongo_client
from app.dependencies import init_dialogue_manager

from app.admin.bots.routes import router as bots_router
from app.admin.entities.routes import router as entities_router
from app.admin.intents.routes import router as intents_router
from app.admin.train.routes import router as train_router
from app.admin.test.routes import router as test_router
from app.admin.integrations.routes import router as integrations_router
from app.admin.chatlogs.routes import router as chatlogs_router


from app.bot.channels.rest.routes import router as rest_router
from app.bot.channels.facebook.routes import router as facebook_router


@asynccontextmanager
async def lifespan(_):
    await init_dialogue_manager()
    yield
    close_mongo_client()


app = FastAPI(title="AI Chatbot Framework", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/live")
async def live():
    # Shallow liveness check - process is up
    return {"status": "alive"}


@app.get("/ready")
async def ready():
    # Lightweight readiness signal (DB and DM checks are covered elsewhere/tests)
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