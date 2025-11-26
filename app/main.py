"""
Dialogue Manager Microservice Entry Point

This is the main entry point for the dialogue manager microservice.
It handles core dialogue processing and state management.
Admin APIs, Chat APIs, and webhook handlers are deployed as separate Lambda functions.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import client as database_client
from app.dependencies import init_dialogue_manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Manage application lifecycle: startup and shutdown.
    
    Initializes dialogue manager on startup and closes database connections on shutdown.
    """
    await init_dialogue_manager()
    yield
    database_client.close()


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        FastAPI: Configured application instance for dialogue manager microservice.
    """
    app = FastAPI(
        title="Dialogue Manager Microservice",
        description="Core dialogue processing and state management service",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Configure CORS for internal service-to-service communication
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict in production to specific service IPs
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check endpoints
    @app.get("/health")
    async def health_check():
        """Kubernetes/ECS health check endpoint."""
        return {"status": "healthy", "service": "dialogue-manager"}

    @app.get("/ready")
    async def readiness_check():
        """Readiness probe for deployment orchestration."""
        return {"status": "ready", "service": "dialogue-manager"}

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "message": "Dialogue Manager Microservice",
            "service": "dialogue-manager",
        }

    return app


# Application instance for ASGI servers (Uvicorn, Gunicorn)
app = create_app()