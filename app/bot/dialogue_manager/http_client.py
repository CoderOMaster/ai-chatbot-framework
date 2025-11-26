import logging
import aiohttp
import asyncio
from typing import Dict, Any, Optional
from aiohttp import ClientTimeout

logger = logging.getLogger("http_client")


class APICallException(Exception):
    """Exception raised for errors during API calls.

    Attributes:
        message: Human readable message describing the error.
        status: Optional HTTP status code returned by the remote service.
        body: Optional response body returned by the remote service.
    """

    def __init__(self, message: str, status: Optional[int] = None, body: Optional[Any] = None):
        super().__init__(message)
        self.status = status
        self.body = body


async def call_api(
    url: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    is_json: bool = False,
    timeout: Optional[float] = 30.0,
    session: Optional[aiohttp.ClientSession] = None,
) -> Dict[str, Any]:
    """Asynchronously call an external API and return a structured result.

    This function is side-effect free with respect to session management when a
    ClientSession is provided by the caller. If no session is provided a temporary
    session is created and closed for the duration of the request. The returned
    dictionary contains the HTTP status, response headers and body (JSON-decoded
    when possible, otherwise text).

    Args:
        url: The API endpoint URL.
        method: HTTP method (GET, POST, PUT, DELETE, etc.).
        headers: Optional request headers.
        parameters: Optional request parameters or body.
        is_json: Whether to send parameters as JSON body for POST/PUT.
        timeout: Request timeout in seconds (applied to the request).
        session: Optional aiohttp.ClientSession to use for the request. If
            provided the session will not be closed by this function.

    Returns:
        A dict with keys: "status" (int), "headers" (dict), and "body".

    Raises:
        APICallException: For transport errors, timeouts, or non-2xx responses.
    """
    headers = headers or {}
    parameters = parameters or {}

    # Prepare timeout object (can be passed to request regardless of session)
    timeout_config = ClientTimeout(total=timeout) if timeout is not None else None

    method = method.upper()
    logger.debug(f"Initiating async API Call: url={url} method={method} payload={parameters}")

    # Prepare request kwargs
    request_kwargs: Dict[str, Any] = {"headers": headers}
    if timeout_config is not None:
        request_kwargs["timeout"] = timeout_config

    if method in ("GET", "DELETE"):
        request_kwargs["params"] = parameters
    elif method in ("POST", "PUT", "PATCH"):  # PATCH included for completeness
        if is_json:
            request_kwargs["json"] = parameters
        else:
            request_kwargs["data"] = parameters
    else:
        # For other methods, pass parameters as data by default
        request_kwargs["data"] = parameters

    async def _perform_request(session_to_use: aiohttp.ClientSession) -> Dict[str, Any]:
        try:
            async with session_to_use.request(method, url, **request_kwargs) as response:
                status = response.status
                try:
                    body = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    body = await response.text()

                headers_out = dict(response.headers)

                if status >= 400:
                    msg = f"HTTP {status} returned for {method} {url}"
                    logger.error(msg + f" - body={body}")
                    raise APICallException(msg, status=status, body=body)

                return {"status": status, "headers": headers_out, "body": body}

        except asyncio.TimeoutError:
            msg = f"Request timed out after {timeout} seconds for {method} {url}"
            logger.error(msg)
            raise APICallException(msg)
        except aiohttp.ClientError as e:
            msg = f"HTTP client error during request to {url}: {str(e)}"
            logger.error(msg)
            raise APICallException(msg)

    # Use provided session if available, otherwise create a temporary one
    if session is not None:
        return await _perform_request(session)
    else:
        async with aiohttp.ClientSession() as temp_session:
            return await _perform_request(temp_session)