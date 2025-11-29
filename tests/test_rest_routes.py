import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, Mock

from app.bot.channels.rest import routes
from app.bot.dialogue_manager.http_client import APICallException
from app.bot.dialogue_manager.models import UserMessage
from app.bot.memory.models import State


class DummyResponse:
    """Minimal stand-in for the HTTP response returned by :func:`call_api`."""

    def __init__(self, body: object) -> None:
        self.body = body


async def _run_process_request(client: routes.DialogueManagerServiceClient, message: UserMessage) -> State:
    """Helper to invoke the client's process method with a sample message."""

    return await client.process(message)


def test_rest_webhook_request_defaults_context() -> None:
    """Ensure the REST webhook payload provides an empty context by default."""

    request = routes.RestWebhookRequest(thread_id="tid", text="hello")
    assert request.context == {}


def test_build_url_trims_slashes() -> None:
    """The HTTP client should normalize slashes when building a request URL."""

    settings = routes.DialogueManagerServiceSettings(
        service_url="https://remote.service/",
        process_endpoint="/dialogue/process",
        timeout=4.0,
    )
    client = routes.DialogueManagerServiceClient(settings)

    assert (
        client._build_url("/dialogue/process")
        == "https://remote.service/dialogue/process"
    )
    assert (
        client._build_url("dialogue/process")
        == "https://remote.service/dialogue/process"
    )


@pytest.mark.asyncio
async def test_process_forwards_payload_and_returns_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requests should be serialized and forwarded to the dialogue manager service."""

    settings = routes.DialogueManagerServiceSettings(
        service_url="https://remote.service/",
        process_endpoint="/dialogue/process",
        timeout=10.0,
    )
    client = routes.DialogueManagerServiceClient(settings)
    message = UserMessage(thread_id="thread-1", text="hi", context={"foo": "bar"})
    payload = message.to_dict()

    response_payload = {
        "thread_id": "thread-1",
        "bot_message": [{"text": "ok"}],
    }
    fake_response = DummyResponse(body=response_payload)
    fake_call_api = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(routes, "call_api", fake_call_api)

    state = await _run_process_request(client, message)

    assert state.bot_message == response_payload["bot_message"]
    fake_call_api.assert_awaited_once()
    fake_call_api.assert_called_with(
        "https://remote.service/dialogue/process",
        "POST",
        headers={"Content-Type": "application/json"},
        parameters=payload,
        is_json=True,
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_process_raises_when_api_returns_non_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client should raise a descriptive error when the remote payload is invalid."""

    settings = routes.DialogueManagerServiceSettings(
        service_url="https://remote.service/",
        process_endpoint="/dialogue/process",
        timeout=5.0,
    )
    client = routes.DialogueManagerServiceClient(settings)
    message = UserMessage(thread_id="thread-2", text="hi", context={})
    fake_call_api = AsyncMock(return_value=DummyResponse(body="unexpected"))
    monkeypatch.setattr(routes, "call_api", fake_call_api)

    with pytest.raises(routes.DialogueManagerServiceClientError) as exc_info:
        await _run_process_request(client, message)

    assert "unexpected payload" in str(exc_info.value)


@pytest.mark.asyncio
async def test_process_handles_state_deserialization_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard against unexpected state shapes returned by the dialogue manager service."""

    settings = routes.DialogueManagerServiceSettings(
        service_url="https://remote.service/",
        process_endpoint="/dialogue/process",
        timeout=5.0,
    )
    client = routes.DialogueManagerServiceClient(settings)
    message = UserMessage(thread_id="thread-3", text="hi", context={})
    response_payload = {
        "thread_id": "thread-3",
        "bot_message": [{"text": "ok"}],
    }
    fake_response = DummyResponse(body=response_payload)
    fake_call_api = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(routes, "call_api", fake_call_api)
    monkeypatch.setattr(
        routes.State,
        "from_dict",
        Mock(side_effect=ValueError("broken payload")),
    )

    with pytest.raises(routes.DialogueManagerServiceClientError) as exc_info:
        await _run_process_request(client, message)

    assert "invalid state" in str(exc_info.value)


@pytest.mark.asyncio
async def test_process_wraps_call_api_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transport failures should be translated into service client errors."""

    settings = routes.DialogueManagerServiceSettings(
        service_url="https://remote.service/",
        process_endpoint="/dialogue/process",
        timeout=5.0,
    )
    client = routes.DialogueManagerServiceClient(settings)
    message = UserMessage(thread_id="thread-4", text="hi", context={})
    fake_call_api = AsyncMock(side_effect=APICallException("timeout"))
    monkeypatch.setattr(routes, "call_api", fake_call_api)

    with pytest.raises(routes.DialogueManagerServiceClientError) as exc_info:
        await _run_process_request(client, message)

    assert "Unable to reach" in str(exc_info.value)


@pytest.mark.asyncio
async def test_process_rest_webhook_request_returns_bot_messages() -> None:
    """The webhook processing helper should return the bot messages from the updated state."""

    request = routes.RestWebhookRequest(thread_id="tid", text="hello", context={"key": "value"})
    state = State(thread_id="tid", bot_message=[{"text": "ok"}])

    class FakeClient:
        def __init__(self, response: State) -> None:
            self.process = AsyncMock(return_value=response)

    client = FakeClient(state)
    messages = await routes.process_rest_webhook_request(request, dialogue_manager_client=client)

    client.process.assert_awaited_once()
    assert messages == state.bot_message


@pytest.mark.asyncio
async def test_process_rest_webhook_request_defaults_empty_list() -> None:
    """Return an empty list when the dialogue manager state lacks a bot response."""

    request = routes.RestWebhookRequest(thread_id="tid", text="hello")
    state = State(thread_id="tid", bot_message=None)

    class FakeClient:
        def __init__(self, response: State) -> None:
            self.process = AsyncMock(return_value=response)

    client = FakeClient(state)
    messages = await routes.process_rest_webhook_request(request, dialogue_manager_client=client)

    assert messages == []


@pytest.mark.asyncio
async def test_webhook_translates_service_errors_to_http_exception() -> None:
    """The REST endpoint should convert downstream client errors into HTTP 502 responses."""

    request = routes.RestWebhookRequest(thread_id="tid", text="hello")

    class FaultyClient:
        def __init__(self) -> None:
            self.process = AsyncMock(side_effect=routes.DialogueManagerServiceClientError("boom"))

    client = FaultyClient()

    with pytest.raises(HTTPException) as exc_info:
        await routes.webbook(request, dialogue_manager_client=client)

    assert exc_info.value.status_code == 502
    assert "boom" in exc_info.value.detail


@pytest.mark.asyncio
async def test_webhook_returns_response_on_success() -> None:
    """The REST endpoint should forward the dialogue manager results unchanged."""

    request = routes.RestWebhookRequest(thread_id="tid", text="hello")
    state = State(thread_id="tid", bot_message=[{"text": "ok"}])

    class HealthyClient:
        def __init__(self, response: State) -> None:
            self.process = AsyncMock(return_value=response)

    client = HealthyClient(state)
    result = await routes.webbook(request, dialogue_manager_client=client)

    assert result == state.bot_message
    client.process.assert_awaited_once()