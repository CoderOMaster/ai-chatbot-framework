import logging
import aiohttp
import asyncio
from typing import Dict, Any, Optional
from aiohttp import ClientTimeout
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("http_client")


class APICallException(Exception):
    """Exception raised for API call failures."""
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
    reraise=True,
)
async def call_api(
    url: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    is_json: bool = False,
    timeout: int = 30,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """
    Asynchronously call external API with retry logic, timeout management, and structured logging.

    This function centralizes all outbound HTTP calls with automatic retry handling
    using exponential backoff and comprehensive error logging.

    Args:
        url: The API endpoint URL
        method: HTTP method (GET, POST, PUT, DELETE)
        headers: Optional request headers
        parameters: Optional request parameters or body
        is_json: Whether to send parameters as JSON body
        timeout: Request timeout in seconds (default: 30)
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        Dict containing the API response

    Raises:
        APICallException: For HTTP-specific errors or timeout errors
        ValueError: For invalid HTTP method types
        Exception: For other unexpected errors

    Example:
        >>> response = await call_api(
        ...     url="https://api.example.com/data",
        ...     method="GET",
        ...     headers={"Authorization": "Bearer token"},
        ...     timeout=30
        ... )
    """
    headers = headers or {}
    parameters = parameters or {}
    timeout_config = ClientTimeout(total=timeout)

    try:
        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            method_upper = method.upper()
            
            logger.debug(
                f"Initiating async API call",
                extra={
                    "url": url,
                    "method": method_upper,
                    "payload_keys": list(parameters.keys()) if parameters else [],
                    "timeout": timeout,
                }
            )

            if method_upper == "GET":
                async with session.get(
                    url, headers=headers, params=parameters
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    
            elif method_upper in ["POST", "PUT"]:
                kwargs = {
                    "headers": headers,
                    ("json" if is_json else "params"): parameters,
                }
                async with getattr(session, method_upper.lower())(url, **kwargs) as response:
                    response.raise_for_status()
                    result = await response.json()
                    
            elif method_upper == "DELETE":
                async with session.delete(
                    url, headers=headers, params=parameters
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    
            else:
                raise ValueError(f"Unsupported HTTP method: {method_upper}")

            logger.debug(
                f"API call successful",
                extra={
                    "url": url,
                    "method": method_upper,
                    "response_keys": list(result.keys()) if isinstance(result, dict) else "non-dict",
                }
            )
            return result

    except aiohttp.ClientError as e:
        logger.error(
            f"HTTP client error occurred",
            extra={
                "url": url,
                "method": method.upper(),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise APICallException(f"HTTP error occurred: {str(e)}") from e
        
    except asyncio.TimeoutError:
        logger.error(
            f"Request timeout",
            extra={
                "url": url,
                "method": method.upper(),
                "timeout_seconds": timeout,
            },
            exc_info=True,
        )
        raise APICallException(f"Request timed out after {timeout} seconds") from None
        
    except ValueError as e:
        logger.error(
            f"Invalid request configuration",
            extra={
                "url": url,
                "method": method.upper(),
                "error": str(e),
            },
            exc_info=True,
        )
        raise
        
    except Exception as e:
        logger.error(
            f"Unexpected error during API call",
            extra={
                "url": url,
                "method": method.upper(),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise