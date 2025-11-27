import asyncio
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

import aiohttp
from aiohttp import ClientResponse, ClientTimeout

logger = logging.getLogger("http_client")


class APICallException(Exception):
    """Raised when an API call ultimately fails after retries."""


# Backwards compatibility with previous misspelled name
APICallExcetion = APICallException


RequestHook = Callable[[Dict[str, Any]], None]
ResponseHook = Callable[[Dict[str, Any]], None]


_shared_session: Optional[aiohttp.ClientSession] = None


def get_shared_session(timeout: Optional[int] = None) -> aiohttp.ClientSession:
    """Return a module-level shared aiohttp.ClientSession singleton.

    The session is created lazily. Callers (typically application startup/shutdown)
    may close the session by calling .close() on it when the application is
    terminating.

    Args:
        timeout: Optional default timeout in seconds for the session.

    Returns:
        aiohttp.ClientSession: a shared ClientSession instance
    """
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        timeout_cfg = ClientTimeout(total=timeout) if timeout else None
        _shared_session = aiohttp.ClientSession(timeout=timeout_cfg)
        logger.debug("Created new shared aiohttp ClientSession", extra={"timeout": timeout})
    return _shared_session


class HttpClient:
    """HTTP client wrapper around aiohttp with retry/backoff and structured hooks.

    This class prefers dependency injection of an aiohttp.ClientSession. If none
    is provided it will lazily obtain a module-level shared session from
    get_shared_session().

    Args:
        session: Optional aiohttp.ClientSession to use.
        default_timeout: Optional default timeout in seconds for requests when not
            provided per-call.
        request_hook: Optional callable invoked before each request with a dict of
            structured fields (url, method, headers, parameters, attempt).
        response_hook: Optional callable invoked after a response is received with
            structured fields (status, url, elapsed, attempt, body_preview).
    """

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        default_timeout: Optional[int] = None,
        request_hook: Optional[RequestHook] = None,
        response_hook: Optional[ResponseHook] = None,
    ) -> None:
        self._session = session
        self._default_timeout = default_timeout
        self._request_hook = request_hook
        self._response_hook = response_hook

    @property
    def session(self) -> aiohttp.ClientSession:
        """Return the configured session, creating the shared one if necessary."""
        if self._session is None or self._session.closed:
            self._session = get_shared_session(timeout=self._default_timeout)
        return self._session

    async def call_api(
        self,
        url: str,
        method: str,
        headers: Optional[Dict[str, str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        is_json: bool = False,
        timeout: Optional[int] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        retry_on_status: Optional[Iterable[int]] = None,
    ) -> Union[Dict[str, Any], str]:
        """Make an HTTP request with retry and backoff semantics.

        Args:
            url: Target URL.
            method: HTTP method (GET, POST, PUT, DELETE, etc.).
            headers: Optional headers.
            parameters: Query parameters or JSON body depending on is_json.
            is_json: Whether to send parameters as JSON body (True) or query params.
            timeout: Per-call timeout in seconds. If None falls back to default_timeout.
            max_retries: Maximum number of attempts (including the first).
            backoff_factor: Base backoff factor used for exponential backoff.
            retry_on_status: Iterable of HTTP status codes that should trigger a retry.

        Returns:
            Parsed JSON (dict/list) when response contains JSON, otherwise text body.

        Raises:
            APICallException: When the call fails after all retries.
        """
        headers = headers or {}
        parameters = parameters or {}
        method = method.upper()
        attempt = 0
        retry_status_set = set(retry_on_status or [502, 503, 504])

        while attempt < max_retries:
            attempt += 1
            extra_log = {"url": url, "method": method, "attempt": attempt}
            try:
                # Hook before request (structured)
                if self._request_hook:
                    try:
                        self._request_hook({**extra_log, "headers": headers, "parameters": parameters})
                    except Exception as hook_exc:  # don't let hooks break requests
                        logger.debug("request_hook raised an exception", exc_info=hook_exc, extra=extra_log)

                req_timeout = ClientTimeout(total=timeout) if timeout is not None else None

                request_kwargs: Dict[str, Any] = {"headers": headers}
                if method == "GET" or not is_json and method in ("GET", "DELETE"):
                    request_kwargs["params"] = parameters
                else:
                    if is_json:
                        request_kwargs["json"] = parameters
                    else:
                        request_kwargs["params"] = parameters

                logger.debug("Performing HTTP request", extra={**extra_log, "request_kwargs": {k: (v if k != 'json' else '<<json>>') for k, v in request_kwargs.items()}})

                async with self.session.request(method, url, timeout=req_timeout, **request_kwargs) as resp:
                    status = resp.status
                    elapsed = resp.headers.get("X-Response-Time") or None

                    # Hook after receiving response
                    preview = None
                    try:
                        # Try to read a small preview for logging without consuming too much memory
                        content_preview = await resp.text()
                        preview = content_preview[:512]
                    except Exception:
                        preview = None

                    if self._response_hook:
                        try:
                            self._response_hook({"url": url, "status": status, "attempt": attempt, "body_preview": preview})
                        except Exception as hook_exc:
                            logger.debug("response_hook raised an exception", exc_info=hook_exc, extra=extra_log)

                    # If the status is in retry set, raise to trigger retry logic
                    if status in retry_status_set:
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=f"Retryable status {resp.status}",
                            headers=resp.headers,
                        )

                    # Raise for other 4xx/5xx errors
                    try:
                        resp.raise_for_status()
                    except aiohttp.ClientResponseError as cre:
                        logger.error("Non-retryable HTTP error", extra={**extra_log, "status": status})
                        raise

                    # Try to decode JSON, fall back to text
                    try:
                        result = await resp.json()
                    except Exception:
                        result = await resp.text()

                    logger.debug("API response received", extra={**extra_log, "status": status, "body_preview": preview})
                    return result

            except (aiohttp.ClientResponseError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                is_last = attempt >= max_retries
                logger.warning("HTTP request attempt failed", extra={**extra_log, "error": str(exc), "is_last": is_last})

                if is_last:
                    logger.error("All retries exhausted for HTTP request", extra={**extra_log, "error": str(exc)})
                    raise APICallException(f"API call failed after {attempt} attempts: {exc}") from exc

                # Exponential backoff
                backoff = backoff_factor * (2 ** (attempt - 1))
                jitter = min(0.1 * backoff, 0.1)
                sleep_for = backoff + (jitter * (0.5 - (asyncio.get_running_loop().time() % 1)))
                logger.debug("Retrying after backoff", extra={**extra_log, "backoff": backoff, "sleep": sleep_for})
                await asyncio.sleep(sleep_for)
            except Exception as exc:  # unexpected
                logger.exception("Unexpected error during API call", extra=extra_log)
                raise


# Convenience default client and function for backwards compatibility
_default_client: Optional[HttpClient] = None


def get_default_client() -> HttpClient:
    """Return a default HttpClient (lazily created)."""
    global _default_client
    if _default_client is None:
        _default_client = HttpClient()
    return _default_client


async def call_api(
    url: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    is_json: bool = False,
    timeout: Optional[int] = None,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    retry_on_status: Optional[Iterable[int]] = None,
) -> Union[Dict[str, Any], str]:
    """Module-level convenience wrapper around HttpClient.call_api for compatibility.

    This keeps existing call sites working while encouraging callers to create
    and inject their own HttpClient instances when they want finer control.
    """
    client = get_default_client()
    return await client.call_api(
        url,
        method,
        headers=headers,
        parameters=parameters,
        is_json=is_json,
        timeout=timeout,
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        retry_on_status=retry_on_status,
    )