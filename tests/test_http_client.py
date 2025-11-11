import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp

from app.bot.dialogue_manager.http_client import call_api, APICallExcetion


class FakeResponse:
    def __init__(self, data, raise_for_status_exc=None):
        self._data = data
        self._raise_for_status_exc = raise_for_status_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        await asyncio.sleep(0)  # ensure this is truly async
        return self._data

    def raise_for_status(self):
        if self._raise_for_status_exc:
            raise self._raise_for_status_exc


class FakeClientSession:
    """
    Minimal async context-managed fake for aiohttp.ClientSession
    Records the last call kwargs for verification.
    """

    def __init__(self, timeout=None, behavior=None):
        self.timeout = timeout
        # behavior: dict mapping method name to a callable returning FakeResponse or raising
        self.behavior = behavior or {}
        self.last_call = SimpleNamespace(method=None, url=None, kwargs=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def _call(self, method, url, **kwargs):
        self.last_call = SimpleNamespace(method=method, url=url, kwargs=kwargs)
        action = self.behavior.get(method)
        if callable(action):
            return action(url, **kwargs)
        return FakeResponse({"ok": True})

    def get(self, url, **kwargs):
        return self._call("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._call("post", url, **kwargs)

    def put(self, url, **kwargs):
        return self._call("put", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._call("delete", url, **kwargs)


@pytest.mark.asyncio
async def test_call_api_get_success_uses_params_and_headers():
    data = {"hello": "world"}

    def behavior_get(url, **kwargs):
        # Ensure params and headers are passed through
        assert kwargs.get("params") == {"q": "x"}
        assert kwargs.get("headers") == {"X": "1"}
        return FakeResponse(data)

    with patch("app.bot.dialogue_manager.http_client.aiohttp.ClientSession",
               lambda timeout=None: FakeClientSession(timeout, behavior={"get": behavior_get})):
        result = await call_api(
            url="http://example.com/test",
            method="GET",
            headers={"X": "1"},
            parameters={"q": "x"},
            is_json=False,
            timeout=5,
        )
        assert result == data


@pytest.mark.asyncio
async def test_call_api_post_json_body_when_is_json_true():
    captured = {}

    def behavior_post(url, **kwargs):
        # aiohttp uses "json" kwarg for JSON body
        captured["json"] = kwargs.get("json")
        captured["params"] = kwargs.get("params")
        return FakeResponse({"status": "ok"})

    with patch("app.bot.dialogue_manager.http_client.aiohttp.ClientSession",
               lambda timeout=None: FakeClientSession(timeout, behavior={"post": behavior_post})):
        result = await call_api(
            url="http://api.example.com/orders",
            method="POST",
            headers={"Content-Type": "application/json"},
            parameters={"a": 1, "b": 2},
            is_json=True,
            timeout=10,
        )
        assert result == {"status": "ok"}
        assert captured["json"] == {"a": 1, "b": 2}
        assert captured["params"] is None


@pytest.mark.asyncio
async def test_call_api_post_params_when_is_json_false():
    captured = {}

    def behavior_post(url, **kwargs):
        captured["json"] = kwargs.get("json")
        captured["params"] = kwargs.get("params")
        return FakeResponse({"status": "ok"})

    with patch("app.bot.dialogue_manager.http_client.aiohttp.ClientSession",
               lambda timeout=None: FakeClientSession(timeout, behavior={"post": behavior_post})):
        result = await call_api(
            url="http://api.example.com/create",
            method="POST",
            headers={"X": "y"},
            parameters={"x": 42},
            is_json=False,
            timeout=10,
        )
        assert result == {"status": "ok"}
        assert captured["json"] is None
        assert captured["params"] == {"x": 42}


@pytest.mark.asyncio
async def test_call_api_raises_api_call_exception_on_http_error():
    def behavior_get(url, **kwargs):
        # Simulate server responds but raises on status check
        return FakeResponse({"error": "nope"}, raise_for_status_exc=aiohttp.ClientError("403"))

    with patch("app.bot.dialogue_manager.http_client.aiohttp.ClientSession",
               lambda timeout=None: FakeClientSession(timeout, behavior={"get": behavior_get})):
        with pytest.raises(APICallExcetion):
            await call_api(
                url="http://example.com/forbidden",
                method="GET",
                headers=None,
                parameters=None,
                is_json=False,
                timeout=3,
            )


@pytest.mark.asyncio
async def test_call_api_raises_api_call_exception_on_timeout():
    def behavior_get(url, **kwargs):
        # Simulate timeout during request context creation
        async def _enter_then_timeout(*a, **k):
            raise asyncio.TimeoutError
        # Return an object that raises TimeoutError on __aenter__
        class _Ctx:
            async def __aenter__(self_):
                raise asyncio.TimeoutError
            async def __aexit__(self_, exc_type, exc, tb):
                return False
        return _Ctx()

    with patch("app.bot.dialogue_manager.http_client.aiohttp.ClientSession",
               lambda timeout=None: FakeClientSession(timeout, behavior={"get": behavior_get})):
        with pytest.raises(APICallExcetion):
            await call_api(
                url="http://example.com/slow",
                method="GET",
                headers=None,
                parameters=None,
                is_json=False,
                timeout=1,
            )


@pytest.mark.asyncio
async def test_call_api_unsupported_method_raises_value_error():
    with patch("app.bot.dialogue_manager.http_client.aiohttp.ClientSession",
               lambda timeout=None: FakeClientSession(timeout)):
        with pytest.raises(ValueError):
            await call_api(
                url="http://example.com/anything",
                method="PATCH",  # not supported in implementation
                headers=None,
                parameters=None,
                is_json=False,
                timeout=2,
            )