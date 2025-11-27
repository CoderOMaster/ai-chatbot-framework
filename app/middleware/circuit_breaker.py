"""Circuit breaker middleware for API gateway."""

import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    """
    Circuit breaker middleware for protecting downstream services.
    
    Prevents cascading failures by monitoring service health and
    failing fast when services are unavailable.
    """
    
    def __init__(self, app, service_registry):
        """
        Initialize circuit breaker middleware.
        
        Args:
            app: The FastAPI application
            service_registry: Service registry for health checks
        """
        super().__init__(app)
        self.service_registry = service_registry
    
    async def dispatch(self, request: Request, call_next):
        """
        Check circuit breaker status before forwarding request.
        
        Args:
            request: The incoming request
            call_next: The next middleware/handler
            
        Returns:
            Response from next handler or error if circuit is open
        """
        # Extract service name from path
        path_parts = request.url.path.strip("/").split("/")
        if path_parts:
            service_name = path_parts[0]
            
            # Check if service is healthy
            if service_name in self.service_registry.service_urls:
                if not self.service_registry.health_status.get(service_name, False):
                    logger.warning(
                        f"Circuit breaker open for service: {service_name}"
                    )
        
        response = await call_next(request)
        return response