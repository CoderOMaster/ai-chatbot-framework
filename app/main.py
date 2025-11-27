"""
API Gateway Aggregator - Routes requests to downstream microservices.

This module implements the API gateway pattern for the AI Chatbot Framework,
providing service discovery, authentication, request tracing, and circuit breakers
for downstream services.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.middleware.tracing import TracingMiddleware
from app.middleware.circuit_breaker import CircuitBreakerMiddleware


logger = logging.getLogger(__name__)


class ServiceRegistry:
    """Service discovery and health check management."""
    
    def __init__(self, service_urls: dict[str, str]):
        """
        Initialize service registry.
        
        Args:
            service_urls: Mapping of service names to their base URLs
        """
        self.service_urls = service_urls
        self.health_status: dict[str, bool] = {
            service: True for service in service_urls.keys()
        }
    
    def get_service_url(self, service_name: str) -> Optional[str]:
        """Get service URL if healthy, otherwise None."""
        if self.health_status.get(service_name, False):
            return self.service_urls.get(service_name)
        return None
    
    def mark_unhealthy(self, service_name: str) -> None:
        """Mark service as unhealthy."""
        self.health_status[service_name] = False
        logger.warning(f"Service {service_name} marked as unhealthy")
    
    def mark_healthy(self, service_name: str) -> None:
        """Mark service as healthy."""
        self.health_status[service_name] = True
        logger.info(f"Service {service_name} marked as healthy")


# Initialize service registry from environment
service_registry = ServiceRegistry(
    service_urls={
        "admin": settings.ADMIN_SERVICE_URL,
        "bot": settings.BOT_SERVICE_URL,
        "dialogue": settings.DIALOGUE_SERVICE_URL,
    }
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Application lifespan context manager.
    
    Handles startup and shutdown events for the API gateway.
    """
    logger.info("API Gateway starting up")
    yield
    logger.info("API Gateway shutting down")


app = FastAPI(
    title="AI Chatbot Framework - API Gateway",
    description="API Gateway aggregator for microservices",
    version="1.0.0",
    lifespan=lifespan,
)

# Security middleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# Tracing middleware
app.add_middleware(TracingMiddleware)

# Circuit breaker middleware
app.add_middleware(CircuitBreakerMiddleware, service_registry=service_registry)

# Authentication middleware
app.add_middleware(AuthMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
try:
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
except RuntimeError:
    logger.warning("Static files directory not found")


@app.get("/health")
async def health() -> dict:
    """Health check endpoint for load balancers."""
    return {"status": "ok", "service": "api-gateway"}


@app.get("/ready")
async def ready() -> dict:
    """Readiness check endpoint."""
    return {"status": "ready", "service": "api-gateway"}


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "message": "AI Chatbot Framework API Gateway",
        "version": "1.0.0",
    }


@app.get("/services/health")
async def services_health() -> dict:
    """Check health status of all downstream services."""
    return {
        "services": service_registry.health_status,
        "gateway": "healthy",
    }


async def get_http_client() -> httpx.AsyncClient:
    """Dependency for HTTP client."""
    async with httpx.AsyncClient(timeout=settings.SERVICE_TIMEOUT) as client:
        yield client


@app.api_route("/admin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def admin_proxy(
    request: Request,
    path: str,
    client: httpx.AsyncClient = Depends(get_http_client),
) -> JSONResponse:
    """
    Proxy requests to admin service.
    
    Args:
        request: The incoming request
        path: The path to proxy
        client: HTTP client for making requests
        
    Returns:
        Response from admin service
        
    Raises:
        HTTPException: If service is unavailable
    """
    service_url = service_registry.get_service_url("admin")
    if not service_url:
        raise HTTPException(status_code=503, detail="Admin service unavailable")
    
    try:
        url = f"{service_url}/admin/{path}"
        response = await client.request(
            method=request.method,
            url=url,
            headers=request.headers,
            content=await request.body(),
        )
        service_registry.mark_healthy("admin")
        return JSONResponse(
            content=response.json(),
            status_code=response.status_code,
            headers=dict(response.headers),
        )
    except Exception as e:
        logger.error(f"Admin service error: {e}")
        service_registry.mark_unhealthy("admin")
        raise HTTPException(status_code=503, detail="Admin service error")


@app.api_route("/bots/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def bot_proxy(
    request: Request,
    path: str,
    client: httpx.AsyncClient = Depends(get_http_client),
) -> JSONResponse:
    """
    Proxy requests to bot service.
    
    Args:
        request: The incoming request
        path: The path to proxy
        client: HTTP client for making requests
        
    Returns:
        Response from bot service
        
    Raises:
        HTTPException: If service is unavailable
    """
    service_url = service_registry.get_service_url("bot")
    if not service_url:
        raise HTTPException(status_code=503, detail="Bot service unavailable")
    
    try:
        url = f"{service_url}/bots/{path}"
        response = await client.request(
            method=request.method,
            url=url,
            headers=request.headers,
            content=await request.body(),
        )
        service_registry.mark_healthy("bot")
        return JSONResponse(
            content=response.json(),
            status_code=response.status_code,
            headers=dict(response.headers),
        )
    except Exception as e:
        logger.error(f"Bot service error: {e}")
        service_registry.mark_unhealthy("bot")
        raise HTTPException(status_code=503, detail="Bot service error")


@app.api_route("/dialogue/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def dialogue_proxy(
    request: Request,
    path: str,
    client: httpx.AsyncClient = Depends(get_http_client),
) -> JSONResponse:
    """
    Proxy requests to dialogue service.
    
    Args:
        request: The incoming request
        path: The path to proxy
        client: HTTP client for making requests
        
    Returns:
        Response from dialogue service
        
    Raises:
        HTTPException: If service is unavailable
    """
    service_url = service_registry.get_service_url("dialogue")
    if not service_url:
        raise HTTPException(status_code=503, detail="Dialogue service unavailable")
    
    try:
        url = f"{service_url}/dialogue/{path}"
        response = await client.request(
            method=request.method,
            url=url,
            headers=request.headers,
            content=await request.body(),
        )
        service_registry.mark_healthy("dialogue")
        return JSONResponse(
            content=response.json(),
            status_code=response.status_code,
            headers=dict(response.headers),
        )
    except Exception as e:
        logger.error(f"Dialogue service error: {e}")
        service_registry.mark_unhealthy("dialogue")
        raise HTTPException(status_code=503, detail="Dialogue service error")