import asyncio
import types
import pytest

from app.bot.dialogue_manager import http_client as hc


class FakeClientError(Exception):
    pass


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload if payload is not None else {"ok": True}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status >= 400:
            # Simulate aiohttp raising a subclass of ClientError
            raise FakeClientError(f"HTTP {self.status}")


class FakeSession:
    def __init__(self, timeout=None, behavior=None, seen=None):
        self.timeout = timeout
        self.behavior = behavior or {}
        self.seen = seen if seen is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def _make_resp(self, method, url, **kwargs):
        self.seen["method"] = method
        self.seen["url"] = url
        self.seen["kwargs"] = kwargs
        cfg = self.behavior.get(method, {})
        if isinstance(cfg, Exception):
            raise cfg
        status = cfg.get("status", 200)
        payload = cfg.get("payload", {"ok": True})
        return FakeResponse(status=status, payload=payload)

    def get(self, url, **kwargs):
        return self._make_resp("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._make_resp("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._make_resp("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._make_resp("DELETE", url, **kwargs)


@pytest.fixture(autouse=True)
def patch_aiohttp(monkeypatch):
    # Patch aiohttp module used inside http_client
    monkeypatch.setattr(hc, "ClientTimeout", lambda total=None: types.SimpleNamespace(total=total), raising=True)
    fake_aiohttp = types.SimpleNamespace(ClientSession=None, ClientError=FakeClientError)
    monkeypatch.setattr(hc, "aiohttp", fake_aiohttp, raising=True)
    return fake_aiohttp


@pytest.mark.asyncio
async def test_call_api_get_success(monkeypatch, patch_aiohttp):
    seen = {}
    patch_aiohttp.ClientSession = lambda timeout=None: FakeSession(seen=seen)

    result = await hc.call_api(
        url="https://api.example.com/data",
        method="GET",
        headers={"A": "1"},
        parameters={"q": "x"},
        is_json=False,
        timeout=5,
    )

    assert result == {"ok": True}
    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://api.example.com/data")
    assert "params" in seen["kwargs"]
    assert seen["kwargs"]["headers"] == {"A": "1"}


@pytest.mark.asyncio
async def test_call_api_post_json_success(monkeypatch, patch_aiohttp):
    seen = {}
    patch_aiohttp.ClientSession = lambda timeout=None: FakeSession(seen=seen)

    payload = {"x": 1}
    result = await hc.call_api(
        url="https://api.example.com/submit",
        method="POST",
        headers={"B": "2"},
        parameters=payload,
        is_json=True,
        timeout=10,
    )

    assert result == {"ok": True}
    assert seen["method"] == "POST"
    assert seen["kwargs"]["json"] == payload
    assert "params" not in seen["kwargs"]


@pytest.mark.asyncio
async def test_call_api_put_params_success(monkeypatch, patch_aiohttp):
    seen = {}
    patch_aiohttp.ClientSession = lambda timeout=None: FakeSession(seen=seen)

    params = {"a": "b"}
    result = await hc.call_api(
        url="https://api.example.com/put",
        method="PUT",
        headers={},
        parameters=params,
        is_json=False,
        timeout=7,
    )

    assert result == {"ok": True}
    assert seen["method"] == "PUT"
    assert seen["kwargs"]["params"] == params


@pytest.mark.asyncio
async def test_call_api_http_error_raises_custom(monkeypatch, patch_aiohttp):
    seen = {}
    behavior = {"GET": {"status": 500, "payload": {"error": "x"}}}
    patch_aiohttp.ClientSession = lambda timeout=None: FakeSession(seen=seen, behavior=behavior)

    with pytest.raises(hc.APICallExcetion) as ei:
        await hc.call_api(
            url="https://api.example.com/error",
            method="GET",
            headers={},
            parameters={},
            is_json=False,
            timeout=3,
        )
    assert "HTTP error" in str(ei.value)


@pytest.mark.asyncio
async def test_call_api_timeout_raises_custom(monkeypatch, patch_aiohttp):
    seen = {}
    behavior = {"POST": asyncio.TimeoutError()}
    patch_aiohttp.ClientSession = lambda timeout=None: FakeSession(seen=seen, behavior=behavior)

    with pytest.raises(hc.APICallExcetion) as ei:
        await hc.call_api(
            url="https://api.example.com/timeout",
            method="POST",
            headers={},
            parameters={"x": 1},
            is_json=True,
            timeout=1,
        )
    assert "timed out" in str(ei.value)


@pytest.mark.asyncio
async def test_call_api_invalid_method_raises_value_error(monkeypatch, patch_aiohttp):
    seen = {}
    patch_aiohttp.ClientSession = lambda timeout=None: FakeSession(seen=seen)

    with pytest.raises(ValueError):
        await hc.call_api(
            url="https://api.example.com/patch",
            method="PATCH",
            headers={},
            parameters={},
            is_json=False,
            timeout=2,
        )