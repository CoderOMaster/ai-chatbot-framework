import asyncio
from typing import Any, Dict, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import ClientTimeout, ContentTypeError

from app.bot.dialogue_manager.http_client import (
    APICallException,
    APICallExcetion,
    HTTPResponse,
    call_api,
)


@pytest.fixture
def default_headers() -> Dict[str, str]:
    """Provide a reusable set of headers for multiple request scenarios."""
    return {"Authorization": "Bearer dummy-token"}


def _make_response_context(
    *,
    status: int = 200,
    json_value: Any = None,
    text_value: str = "",
    headers: Optional[Dict[str, str]] = None,
    json_side_effect: Optional[Exception] = None,
) -> Tuple[AsyncMock, AsyncMock]:
    response = AsyncMock()
    response.status = status
    response.headers = headers or {"Content-Type": "application/json"}
    response.raise_for_status = MagicMock()
    response.text = AsyncMock(return_value=text_value)
    if json_side_effect:
        response.json = AsyncMock(side_effect=json_side_effect)
    else:
        response.json = AsyncMock(return_value=json_value)

    response_context = AsyncMock()
    response_context.__aenter__.return_value = response
    response_context.__aexit__.return_value = None
    return response_context, response


@pytest.mark.asyncio
async def test_call_api_get_success_returns_response_struct(default_headers: Dict[str, str]) -> None:
    """Validate that GET requests return a populated HTTPResponse with JSON bodies."""
    request_payload = {"q": "value"}
    response_context, _ = _make_response_context(json_value={"ok": True}, headers={"Content-Type": "application/json"})
    session = AsyncMock()
    session.request = MagicMock(return_value=response_context)

    result = await call_api(
        url="https://example.com/data",
        method="GET",
        headers=default_headers,
        parameters=request_payload,
        session=session,
    )

    assert isinstance(result, HTTPResponse)
    assert result.status == 200
    assert result.body == {"ok": True}
    assert result.headers["Content-Type"] == "application/json"

    session.request.assert_called_once()
    _, request_kwargs = session.request.call_args
    assert request_kwargs["params"] == request_payload
    assert request_kwargs["headers"] == default_headers
    assert "json" not in request_kwargs


@pytest.mark.asyncio
async def test_call_api_post_json_payload_includes_json_key(default_headers: Dict[str, str]) -> None:
    """Ensure POST requests with is_json=True serialize payloads under the 'json' key."""
    response_context, _ = _make_response_context(json_value={"created": True})
    session = AsyncMock()
    session.request = MagicMock(return_value=response_context)

    data = {"name": "bot"}
    await call_api(
        url="https://example.com/create",
        method="POST",
        headers=default_headers,
        parameters=data,
        is_json=True,
        session=session,
    )

    _, request_kwargs = session.request.call_args
    assert request_kwargs["json"] == data
    assert "params" not in request_kwargs


@pytest.mark.asyncio
async def test_call_api_post_without_json_uses_params(default_headers: Dict[str, str]) -> None:
    """When is_json=False, non-GET methods should reuse 'params' for payload transmission."""
    response_context, _ = _make_response_context(json_value={"status": "ok"})
    session = AsyncMock()
    session.request = MagicMock(return_value=response_context)

    data = {"limit": 5}
    await call_api(
        url="https://example.com/update",
        method="PATCH",
        headers=default_headers,
        parameters=data,
        is_json=False,
        session=session,
    )

    _, request_kwargs = session.request.call_args
    assert request_kwargs["params"] == data
    assert "json" not in request_kwargs


@pytest.mark.asyncio
async def test_call_api_falls_back_to_text_body(default_headers: Dict[str, str]) -> None:
    """ContentTypeError should cause call_api to use raw text fallback instead of JSON."""
    error = ContentTypeError(request_info=None, history=(), message="expected json")
    response_context, response = _make_response_context(
        text_value="<html>error</html>",
        json_side_effect=error,
    )
    session = AsyncMock()
    session.request = MagicMock(return_value=response_context)

    result = await call_api(
        url="https://example.com/malformed",
        method="GET",
        headers=default_headers,
        session=session,
    )

    assert result.body == "<html>error</html>"
    response.text.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_api_uses_provided_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that supplying a ClientSession bypasses managed session creation."""
    response_context, _ = _make_response_context(json_value={"ok": True})
    provided_session = AsyncMock()
    provided_session.request = MagicMock(return_value=response_context)

    def _should_not_be_called(*args: Any, **kwargs: Any) -> AsyncMock:
        raise AssertionError("ClientSession should not be instantiated when a session is passed")

    monkeypatch.setattr(aiohttp, "ClientSession", _should_not_be_called)

    await call_api(
        url="https://example.com/using-session",
        method="GET",
        session=provided_session,
    )

    provided_session.request.assert_called_once()


@pytest.mark.asyncio
async def test_call_api_manages_internal_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling without a session should create and use aiohttp.ClientSession with the configured timeout."""
    response_context, _ = _make_response_context(json_value={"ok": True})
    fake_session = AsyncMock()
    fake_session.request = MagicMock(return_value=response_context)

    client_session_cm = AsyncMock()
    client_session_cm.__aenter__.return_value = fake_session
    client_session_cm.__aexit__.return_value = None

    client_session_factory = MagicMock(return_value=client_session_cm)
    monkeypatch.setattr(aiohttp, "ClientSession", client_session_factory)

    result = await call_api(
        url="https://example.com/manual",
        method="GET",
    )

    assert result.body == {"ok": True}
    client_session_factory.assert_called_once()
    timeout_used = client_session_factory.call_args.kwargs.get("timeout")
    assert isinstance(timeout_used, ClientTimeout)
    assert timeout_used.total == 30.0
    client_session_cm.__aenter__.assert_awaited_once()
    client_session_cm.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_api_raises_api_call_exception_on_client_error(default_headers: Dict[str, str]) -> None:
    """Transport level client errors should be wrapped inside APICallException."""
    session = AsyncMock()
    session.request = MagicMock(side_effect=aiohttp.ClientError("boom"))

    with pytest.raises(APICallException):
        await call_api(
            url="https://example.com/error",
            method="GET",
            headers=default_headers,
            session=session,
        )


@pytest.mark.asyncio
async def test_call_api_raises_api_call_exception_on_timeout(default_headers: Dict[str, str]) -> None:
    """Timeout errors should also translate to APICallException to keep the call site consistent."""
    session = AsyncMock()
    session.request = MagicMock(side_effect=asyncio.TimeoutError("timeout"))

    with pytest.raises(APICallException):
        await call_api(
            url="https://example.com/timeout",
            method="GET",
            headers=default_headers,
            session=session,
        )


def test_apicall_exception_alias_matches() -> None:
    """The historically misspelled alias must continue to reference the same exception class."""
    assert APICallExcetion is APICallException


@pytest.mark.asyncio
async def test_call_api_unsupported_method_raises_value_error() -> None:
    """Invalid HTTP methods should raise ValueError before any network activity occurs."""
    with pytest.raises(ValueError):
        await call_api(
            url="https://example.com/invalid",
            method="TRACE",
        )