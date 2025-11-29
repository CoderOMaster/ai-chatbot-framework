from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock

from app.admin.test.routes import (
    chat,
    get_dialogue_manager_service_client,
)
from app.dependencies import DialogueManagerClient, DialogueManagerClientException
from app.bot.dialogue_manager.models import UserMessage


class _FakeState:
    """A simple stand-in for the remote dialogue manager state object."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return self._payload


@pytest.fixture
def baseline_body() -> Dict[str, Any]:
    """Provide a sample payload that resembles what the admin client sends."""

    return {
        "thread_id": "thread-999",
        "text": "diagnostic text",
        "context": {"foo": "bar"},
    }


def _build_client_with_process(process_mock: AsyncMock) -> Any:
    """Helper that attaches an async process method to a simple namespace object."""

    client = SimpleNamespace()
    client.process = process_mock
    return client


@pytest.mark.asyncio
async def test_get_dialogue_manager_service_client_returns_client() -> None:
    """Ensure the guard dependency returns the remote client when available."""

    dialogue_client = DialogueManagerClient(
        base_url="http://example.com",
        process_endpoint="/process",
        reload_endpoint="/reload",
        timeout=5.0,
    )

    resolved_client = await get_dialogue_manager_service_client(dialogue_client)

    assert resolved_client is dialogue_client


@pytest.mark.asyncio
async def test_get_dialogue_manager_service_client_rejects_invalid_dependency() -> None:
    """The guard should raise HTTP 500 if a local dialogue manager is injected."""

    with pytest.raises(HTTPException) as exc_info:
        await get_dialogue_manager_service_client(object())

    assert exc_info.value.status_code == 500
    assert "dialogue-manager-service" in exc_info.value.detail


@pytest.mark.asyncio
async def test_chat_proxies_user_message_and_returns_state(baseline_body: Dict[str, Any]) -> None:
    """Verify a diagnostic request is translated into a UserMessage and the returned state is serialized."""

    state_payload = {"thread_id": baseline_body["thread_id"], "status": "ok"}
    fake_state = _FakeState(state_payload)
    process_mock = AsyncMock(return_value=fake_state)
    client = _build_client_with_process(process_mock)

    response = await chat(baseline_body, dialogue_manager_client=client)

    assert response == state_payload

    process_mock.assert_awaited_once()
    user_message_arg = process_mock.call_args.args[0]
    assert isinstance(user_message_arg, UserMessage)
    assert user_message_arg.thread_id == baseline_body["thread_id"]
    assert user_message_arg.text == baseline_body["text"]
    assert user_message_arg.context == baseline_body["context"]


@pytest.mark.asyncio
async def test_chat_default_context_when_missing() -> None:
    """The request should synthesize an empty context when the client omits it."""

    body = {"thread_id": "thread-default", "text": "no context"}
    fake_state = _FakeState({"thread_id": body["thread_id"], "ok": True})
    process_mock = AsyncMock(return_value=fake_state)
    client = _build_client_with_process(process_mock)

    await chat(body, dialogue_manager_client=client)

    process_mock.assert_awaited_once()
    user_message_arg = process_mock.call_args.args[0]
    assert user_message_arg.context == {}


@pytest.mark.asyncio
async def test_chat_translates_client_exceptions_to_http_502() -> None:
    """Failures from the remote client should surface as HTTP 502 responses."""

    process_mock = AsyncMock(side_effect=DialogueManagerClientException("timeout"))
    client = _build_client_with_process(process_mock)
    body = {"thread_id": "thread-error", "text": "boom"}

    with pytest.raises(HTTPException) as exc_info:
        await chat(body, dialogue_manager_client=client)

    assert exc_info.value.status_code == 502
    assert "timeout" in exc_info.value.detail

    process_mock.assert_awaited_once()