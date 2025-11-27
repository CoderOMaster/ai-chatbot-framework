import time
import types
import pytest
from fastapi import HTTPException

from app.bot.channels.rest import routes
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def clear_request_counts():
    """Clear global request counts before each test to avoid cross-test pollution."""
    routes._request_counts.clear()
    yield
    routes._request_counts.clear()


def test_router_has_webhook_route():
    """Validate that the router exposes the corrected '/rest/webhook' endpoint path."""
    paths = [r.path for r in routes.router.routes]
    assert "/rest/webhook" in paths


def test_webhook_request_validators_trim_and_requirements():
    """WebhookRequest should trim whitespace and enforce non-empty constraints and length."""
    # Trimming
    req = routes.WebhookRequest(thread_id="  thread1  ", text="  hello world  ")
    assert req.thread_id == "thread1"
    assert req.text == "hello world"

    # Empty thread_id
    with pytest.raises(ValidationError):
        routes.WebhookRequest(thread_id="   ", text="ok")

    # Empty text
    with pytest.raises(ValidationError):
        routes.WebhookRequest(thread_id="t", text="   ")

    # Too long text
    long_text = "x" * (routes.WebhookRequest.__fields__["text"].field_info.max_length + 1)
    with pytest.raises(ValidationError):
        routes.WebhookRequest(thread_id="t", text=long_text)


def test_check_rate_limit_exceeds_after_max():
    """Once the maximum requests per minute is exceeded, check_rate_limit returns False."""
    import time
    current_minute = int(time.time() / 60)
    client = "1.2.3.4"
    key = f"{client}:{current_minute}"

    # Set count to MAX so the next check increments to MAX+1 and should return False
    routes._request_counts[key] = routes.MAX_REQUESTS_PER_MINUTE
    assert routes._check_rate_limit(client) is False


@pytest.mark.asyncio
async def test_call_dialogue_manager_service_success(monkeypatch):
    """_call_dialogue_manager_service should return parsed JSON on successful HTTP call."""

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"bot_message": "hi", "context": {"k": "v"}}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return DummyResponse()

    # Patch the httpx.AsyncClient used in routes
    monkeypatch.setattr(routes.httpx, "AsyncClient", DummyClient)

    user_message = routes.UserMessage(thread_id="t1", text="hello", context={})
    resp = await routes._call_dialogue_manager_service(user_message=user_message, request_id="rid")
    assert resp["bot_message"] == "hi"
    assert resp["context"]["k"] == "v"


@pytest.mark.asyncio
async def test_call_dialogue_manager_service_http_error(monkeypatch):
    """If httpx raises HTTPError, _call_dialogue_manager_service should raise HTTPException with 503."""

    class BrokenClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise routes.httpx.HTTPError("boom")

    monkeypatch.setattr(routes.httpx, "AsyncClient", BrokenClient)

    user_message = routes.UserMessage(thread_id="t1", text="hello", context={})
    with pytest.raises(HTTPException) as exc:
        await routes._call_dialogue_manager_service(user_message=user_message, request_id="rid")

    assert exc.value.status_code == 503
    assert "Dialogue manager service unavailable" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_call_dialogue_manager_service_unexpected_error(monkeypatch):
    """If an unexpected exception occurs, the function should raise HTTPException with 500."""

    class BrokenClient2:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("unexpected")

    monkeypatch.setattr(routes.httpx, "AsyncClient", BrokenClient2)

    user_message = routes.UserMessage(thread_id="t1", text="hello", context={})
    with pytest.raises(HTTPException) as exc:
        await routes._call_dialogue_manager_service(user_message=user_message, request_id="rid")

    assert exc.value.status_code == 500
    assert "Error communicating with dialogue manager" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_webhook_success_uses_header_request_id(monkeypatch):
    """The webhook should use X-Request-ID header if provided and return the dialogue-manager result."""

    async def fake_call(*, user_message, request_id, dialogue_manager_url=None):
        return {"bot_message": "ok", "context": {"a": 1}}

    monkeypatch.setattr(routes, "_call_dialogue_manager_service", fake_call)

    fake_request = types.SimpleNamespace(client=types.SimpleNamespace(host="5.6.7.8"))
    body = routes.WebhookRequest(thread_id="th", text="hi")

    resp = await routes.webhook(request=fake_request, body=body, x_request_id="my-id")
    assert isinstance(resp, routes.WebhookResponse)
    assert resp.request_id == "my-id"
    assert resp.bot_message == "ok"
    assert resp.context == {"a": 1}


@pytest.mark.asyncio
async def test_webhook_rate_limit_exceeded():
    """If the client exceeds rate limit, webhook should raise HTTPException 429."""
    # Prepare counts to make next request exceed limit
    current_minute = int(time.time() / 60)
    client = "9.9.9.9"
    key = f"{client}:{current_minute}"
    routes._request_counts[key] = routes.MAX_REQUESTS_PER_MINUTE

    fake_request = types.SimpleNamespace(client=types.SimpleNamespace(host=client))
    body = routes.WebhookRequest(thread_id="t", text="ok")

    with pytest.raises(HTTPException) as exc:
        await routes.webhook(request=fake_request, body=body)

    assert exc.value.status_code == 429
    assert "Rate limit exceeded" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_webhook_handles_dialogue_manager_exception(monkeypatch):
    """If dialogue manager raises a DialogueManagerException, webhook should map it to HTTP 400."""

    async def raise_dm(*, user_message, request_id, dialogue_manager_url=None):
        raise routes.DialogueManagerException("dmErr")

    monkeypatch.setattr(routes, "_call_dialogue_manager_service", raise_dm)

    fake_request = types.SimpleNamespace(client=types.SimpleNamespace(host="1.1.1.1"))
    body = routes.WebhookRequest(thread_id="t", text="hi")

    with pytest.raises(HTTPException) as exc:
        await routes.webhook(request=fake_request, body=body)

    assert exc.value.status_code == 400
    assert "Dialogue processing error" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_webhook_handles_unexpected_exception(monkeypatch):
    """If an unexpected exception occurs during processing, webhook should return HTTP 500."""

    async def raise_unexpected(*, user_message, request_id, dialogue_manager_url=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(routes, "_call_dialogue_manager_service", raise_unexpected)

    fake_request = types.SimpleNamespace(client=types.SimpleNamespace(host="2.2.2.2"))
    body = routes.WebhookRequest(thread_id="t", text="hi")

    with pytest.raises(HTTPException) as exc:
        await routes.webhook(request=fake_request, body=body)

    assert exc.value.status_code == 500
    assert "Internal server error" in str(exc.value.detail)