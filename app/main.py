"""
FastAPI application factory and composition root.

Sets up the FastAPI application with middleware, routes, and lifecycle management.
This serves as the composition root for the monolithic backend, wiring together
all routers and managing shared resources (database, dialogue manager).

Deployment Patterns:
- Monolith: Runs with full database and dialogue manager initialization
- Split Services: Individual services (dialogue-manager, admin-training-api)
  can override the lifespan to skip unnecessary initializations
"""

from contextlib import asynccontextmanager
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, APIRouter
import logging

from app.database import init_db, close_db
from app.dependencies import init_dialogue_manager, get_dialogue_manager
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

logger = logging.getLogger(__name__)


def _should_init_database() -> bool:
    """
    Determine if database initialization should be performed.
    
    Returns True for monolith deployments, False for split services
    that don't need database access.
    
    Returns:
        bool: True if database should be initialized
    """
    settings = get_settings()
    # Check if this service is configured to use database
    # For now, always initialize in monolith mode
    return True


def _should_init_dialogue_manager() -> bool:
    """
    Determine if dialogue manager initialization should be performed.
    
    Returns True for monolith deployments and dialogue-manager service,
    False for API-only services that use remote dialogue manager.
    
    Returns:
        bool: True if dialogue manager should be initialized
    """
    settings = get_settings()
    # If DIALOGUE_MANAGER_SERVICE_URL is set, we're using remote service
    # and should not initialize locally
    dialogue_manager_service_url = getattr(
        settings, "DIALOGUE_MANAGER_SERVICE_URL", None
    )
    return not bool(dialogue_manager_service_url)


@asynccontextmanager
async def lifespan(_):
    """
    Application lifespan context manager.
    
    Handles startup and shutdown of application resources including
    database connections and dialogue manager initialization.
    
    For split service deployments, individual services can override
    this to skip unnecessary initializations.
    """
    # Startup
    logger.info("Starting FastAPI application")
    
    if _should_init_database():
        logger.info("Initializing database connection")
        settings = get_settings()
        await init_db(settings)
    
    if _should_init_dialogue_manager():
        logger.info("Initializing dialogue manager")
        await init_dialogue_manager()
    
    yield
    
    # Shutdown
    logger.info("Shutting down FastAPI application")
    
    if _should_init_database():
        logger.info("Closing database connection")
        await close_db()


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
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/")
async def root():
    """Root endpoint with welcome message."""
    return {"message": "Welcome to AI Chatbot Framework API"}


# Admin APIs - composition of admin routers
admin_router = APIRouter(prefix="/admin")
admin_router.include_router(bots_router)
admin_router.include_router(intents_router)
admin_router.include_router(entities_router)
admin_router.include_router(train_router)
admin_router.include_router(test_router)
admin_router.include_router(integrations_router)
admin_router.include_router(chatlogs_router)

app.include_router(admin_router)

# Bot channel APIs - composition of channel routers
bot_router = APIRouter(prefix="/bots/channels", tags=["channels"])
bot_router.include_router(rest_router, tags=["rest"])
bot_router.include_router(facebook_router, tags=["facebook"])

app.include_router(bot_router)