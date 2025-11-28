from __future__ import annotations

from dataclasses import dataclass
import asyncio
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import ClientSession, ClientTimeout, ContentTypeError


class APICallException(Exception):
    """Raised when an outbound HTTP request fails."""


# Maintain backwards compatibility for the original typo.
APICallExcetion = APICallException


@dataclass(frozen=True)
class HTTPResponse:
    """Structured payload returned by :func:`call_api`."""

    status: int
    body: Any
    headers: Dict[str, str]


async def call_api(
    url: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    is_json: bool = False,
    timeout: float = 30.0,
    session: Optional[ClientSession] = None,
) -> HTTPResponse:
    """Execute an HTTP request and return structured response data.

    Args:
        url: The target endpoint.
        method: Request method (GET, POST, PUT, DELETE, PATCH).
        headers: Optional request headers.
        parameters: Optional JSON or query parameters.
        is_json: Toggle JSON serialization for non-GET methods.
        timeout: Request timeout in seconds.
        session: Optional shared aiohttp client session.

    Returns:
        HTTPResponse: Populated status, body, and headers from the remote service.

    Raises:
        ValueError: If an unsupported HTTP method is provided.
        APICallException: For transport, timeout, or status failures.
    """
    allowed_methods = {"GET", "POST", "PUT", "DELETE", "PATCH"}
    method = method.upper()
    if method not in allowed_methods:
        raise ValueError(f"Unsupported request method: {method}")

    header_values = headers or {}
    param_values = parameters or {}
    request_kwargs: Dict[str, Any] = {"headers": header_values}

    if method == "GET":
        if param_values:
            request_kwargs["params"] = param_values
    else:
        payload_key = "json" if is_json else "params"
        if param_values:
            request_kwargs[payload_key] = param_values

    timeout_config = ClientTimeout(total=timeout)

    async def _perform_request(active_session: ClientSession) -> HTTPResponse:
        async with active_session.request(
            method, url, timeout=timeout_config, **request_kwargs
        ) as response:
            response.raise_for_status()
            try:
                body: Any = await response.json()
            except ContentTypeError:
                body = await response.text()
            return HTTPResponse(
                status=response.status,
                body=body,
                headers=dict(response.headers),
            )

    try:
        if session is None:
            async with aiohttp.ClientSession(timeout=timeout_config) as managed_session:
                return await _perform_request(managed_session)
        return await _perform_request(session)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise APICallException(f"HTTP request failed: {exc}") from exc