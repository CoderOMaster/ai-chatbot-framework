"""Authentication middleware for API gateway."""

import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware for validating requests."""
    
    async def dispatch(self, request: Request, call_next):
        """
        Process request and validate authentication.
        
        Args:
            request: The incoming request
            call_next: The next middleware/handler
            
        Returns:
            Response from next handler or error response
        """
        # Skip auth for health checks
        if request.url.path in ["/health", "/ready", "/"]:
            return await call_next(request)
        
        # Add authentication logic here
        # For now, pass through all requests
        response = await call_next(request)
        return response