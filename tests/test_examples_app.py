"""
Tests for examples/python/app.py

These tests load the example module directly from its file path to avoid import/package issues
and use mocking to simulate network interactions.
"""
from typing import Any, Dict
import importlib.util
import pathlib
import sys
import json
import builtins
from unittest.mock import patch, Mock
import pytest
import requests


def load_examples_app_module():
    """Dynamically load the examples/python/app.py module for testing."""
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    app_path = repo_root / "examples" / "python" / "app.py"
    spec = importlib.util.spec_from_file_location("examples_app", str(app_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def app_module():
    return load_examples_app_module()


@pytest.fixture
def client(app_module) -> Any:
    """Create a BotClient instance for tests with predictable values."""
    return app_module.BotClient(base_url="http://testserver", api_key="testkey", bot_id="test-bot")


def make_response(json_data: Dict[str, Any], status_code: int = 200):
    """Helper to create a mock requests.Response-like object with json() and raise_for_status()."""
    mock_resp = Mock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data

    def raise_for_status():
        if status_code >= 400:
            raise requests.exceptions.HTTPError(f"Status: {status_code}")

    mock_resp.raise_for_status.side_effect = raise_for_status
    return mock_resp


def test_start_conversation_success_sets_session_id(client, app_module):
    """start_conversation should call the /api/v2/conversations endpoint and set session_id on success."""
    expected = {"session_id": "sess-123", "message": "Welcome!"}

    with patch.object(app_module.requests, "post", return_value=make_response(expected)) as mock_post:
        resp = client.start_conversation()

    assert resp == expected
    assert client.session_id == "sess-123"
    # Verify URL and payload
    mock_post.assert_called_once()
    called_url = mock_post.call_args[0][0]
    assert called_url.endswith("/api/v2/conversations")
    called_json = mock_post.call_args[1]["json"]
    assert called_json == {"bot_id": "test-bot"}
    # Headers include bearer token and bot id
    called_headers = mock_post.call_args[1]["headers"]
    assert called_headers["Authorization"] == "Bearer testkey"
    assert called_headers["X-Bot-ID"] == "test-bot"


def test_start_conversation_raises_on_http_error(client, app_module):
    """start_conversation should propagate request exceptions (HTTP errors)."""
    mock_resp = make_response({"error": "bad"}, status_code=500)
    with patch.object(app_module.requests, "post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.HTTPError):
            client.start_conversation()


def test_send_message_without_session_raises(client):
    """send_message should raise ValueError when no session is active."""
    with pytest.raises(ValueError):
        client.send_message("Hello")


def test_send_message_success_posts_message(client, app_module):
    """With an active session, send_message should post to the messages endpoint and return JSON."""
    client.session_id = "sess-123"
    expected = {"message": "Hi there"}

    with patch.object(app_module.requests, "post", return_value=make_response(expected)) as mock_post:
        resp = client.send_message("Hello")

    assert resp == expected
    mock_post.assert_called_once()
    called_url = mock_post.call_args[0][0]
    assert "/api/v2/conversations/sess-123/messages" in called_url
    assert mock_post.call_args[1]["json"] == {"message": "Hello"}


def test_send_message_propagates_request_exception(client, app_module):
    """send_message should propagate network/request exceptions from requests.post."""
    client.session_id = "sess-123"

    with patch.object(app_module.requests, "post", side_effect=requests.exceptions.RequestException("fail")):
        with pytest.raises(requests.exceptions.RequestException):
            client.send_message("Hello")


def test_get_conversation_history_without_session_raises(client):
    """get_conversation_history should raise ValueError when no session is active."""
    with pytest.raises(ValueError):
        client.get_conversation_history()


def test_get_conversation_history_success_returns_json(client, app_module):
    """With an active session, get_conversation_history should GET the conversation endpoint."""
    client.session_id = "sess-xyz"
    expected = {"messages": [{"from": "bot", "text": "Hello"}]}

    with patch.object(app_module.requests, "get", return_value=make_response(expected)) as mock_get:
        resp = client.get_conversation_history()

    assert resp == expected
    mock_get.assert_called_once()
    called_url = mock_get.call_args[0][0]
    assert called_url.endswith(f"/api/v2/conversations/{client.session_id}")


def test_main_exit_flow_prints_welcome_and_goodbye(monkeypatch, app_module, capsys):
    """main should print the initial bot message and then print goodbye when user types exit."""
    # Patch logging to avoid noisy output
    monkeypatch.setattr(app_module.logging, "basicConfig", lambda **kwargs: None)

    # Create a fake client with patched methods
    fake_client = Mock()
    fake_client.start_conversation.return_value = {"message": "Welcome!"}
    fake_client.start_conversation.side_effect = None
    # Ensure session_id is set so send_message could work if called
    fake_client.session_id = "sess-1"
    fake_client.send_message.return_value = {"message": "OK"}

    # Patch the BotClient constructor to return our fake client
    monkeypatch.setattr(app_module, "BotClient", lambda base_url, api_key, bot_id: fake_client)

    # Simulate user input: 'exit' -> causes goodbye message and loop break
    inputs = ["exit"]

    def fake_input(prompt=""):
        return inputs.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)

    # Run main (should not raise)
    app_module.main()

    captured = capsys.readouterr()
    assert "Bot: Welcome!" in captured.out
    assert "Bot: Goodbye!" in captured.out


def test_main_handles_keyboard_interrupt(monkeypatch, app_module, capsys):
    """main should catch KeyboardInterrupt from input and print a conversation ended message."""
    monkeypatch.setattr(app_module.logging, "basicConfig", lambda **kwargs: None)

    fake_client = Mock()
    fake_client.start_conversation.return_value = {"message": "Hello"}
    fake_client.session_id = "sess-2"
    monkeypatch.setattr(app_module, "BotClient", lambda base_url, api_key, bot_id: fake_client)

    def raise_keyboard(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", raise_keyboard)

    app_module.main()

    captured = capsys.readouterr()
    assert "Conversation ended." in captured.out