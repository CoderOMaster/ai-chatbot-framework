"""Request tracing middleware for API gateway."""

import logging
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class TracingMiddleware(BaseHTTPMiddleware):
    """Middleware for request tracing and correlation IDs."""
    
    async def dispatch(self, request: Request, call_next):
        """
        Add tracing headers to request.
        
        Args:
            request: The incoming request
            call_next: The next middleware/handler
            
        Returns:
            Response from next handler with tracing headers
        """
        # Generate or use existing correlation ID
        correlation_id = request.headers.get(
            "X-Correlation-ID",
            str(uuid.uuid4())
        )
        
        # Add to request state
        request.state.correlation_id = correlation_id
        
        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path}",
            extra={"correlation_id": correlation_id}
        )
        
        # Process request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        
        return response