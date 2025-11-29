import base64
import hmac
import json
from unittest.mock import AsyncMock, Mock, MagicMock
from contextlib import asynccontextmanager

import aiohttp
import pytest

from app.bot.channels.facebook import messenger


@pytest.mark.asyncio
async def test_remote_dialogue_manager_client_success() -> None:
    """Ensures RemoteDialogueManagerClient returns parsed JSON when status is 200."""
    session = AsyncMock()
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"bot_message": [{"text": "ok"}]})
    
    # Create a proper async context manager
    @asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield response
    
    session.post = Mock(side_effect=mock_post)

    client = messenger.RemoteDialogueManagerClient("http://service", session)
    user_message = messenger.UserMessage(thread_id="thread", text="hi", context={})
    result = await client.process(user_message)

    assert result == {"bot_message": [{"text": "ok"}]}
    session.post.assert_called_once()


@pytest.mark.asyncio
async def test_remote_dialogue_manager_client_handles_bad_status() -> None:
    """Validates that non-200 responses raise a DialogueManagerClientError."""
    session = AsyncMock()
    response = AsyncMock()
    response.status = 500
    response.text = AsyncMock(return_value="server error")
    
    # Create a proper async context manager
    @asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield response
    
    session.post = Mock(side_effect=mock_post)

    client = messenger.RemoteDialogueManagerClient("http://service", session)
    user_message = messenger.UserMessage(thread_id="thread", text="hi", context={})

    with pytest.raises(messenger.DialogueManagerClientError):
        await client.process(user_message)


@pytest.mark.asyncio
async def test_remote_dialogue_manager_client_handles_network_failure() -> None:
    """Ensures client errors from aiohttp are wrapped in DialogueManagerClientError."""
    session = AsyncMock()
    
    # Create an async context manager that raises an exception
    @asynccontextmanager
    async def mock_post_error(*args, **kwargs):
        raise aiohttp.ClientError("conn failed")
        yield  # This line is never reached but needed for syntax
    
    session.post = Mock(side_effect=mock_post_error)

    client = messenger.RemoteDialogueManagerClient("http://service", session)
    user_message = messenger.UserMessage(thread_id="thread", text="hi", context={})

    with pytest.raises(messenger.DialogueManagerClientError):
        await client.process(user_message)


@pytest.mark.asyncio
async def test_facebook_sender_uses_existing_session_for_success() -> None:
    """FacebookSender should reuse provided session and not raise on successful send."""
    session = AsyncMock()
    response = AsyncMock()
    response.status = 200
    
    # Create a proper async context manager
    @asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield response
    
    session.post = Mock(side_effect=mock_post)

    sender = messenger.FacebookSender("token", session=session)
    await sender.send_message("recipient", {"text": "hello"})

    session.post.assert_called_once()


@pytest.mark.asyncio
async def test_facebook_sender_raises_on_failure() -> None:
    """FacebookSender should surface HTTPException when Facebook rejects the message."""
    session = AsyncMock()
    response = AsyncMock()
    response.status = 400
    response.json = AsyncMock(return_value={"error": "bad"})
    
    # Create a proper async context manager
    @asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield response
    
    session.post = Mock(side_effect=mock_post)

    sender = messenger.FacebookSender("token", session=session)

    with pytest.raises(Exception) as exc_info:
        await sender.send_message("recipient", {"text": "hello"})

    assert "Failed to send message to Facebook" in str(exc_info.value)


def test_facebook_sender_format_bot_response_returns_list() -> None:
    """Bot messages should always be normalized to a list for Facebook."""
    sender = messenger.FacebookSender("token")
    assert sender.format_bot_response({"text": "hi"}) == [{"text": "hi"}]


@pytest.mark.asyncio
async def test_facebook_receiver_handle_message_dispatches() -> None:
    """Receiver should format each bot message and use sender to deliver it."""
    sender = Mock()
    sender.format_bot_response.return_value = [{"text": "pong"}]
    sender.send_message = AsyncMock()

    dialogue_client = Mock()
    dialogue_client.process = AsyncMock(return_value={"bot_message": [{"text": "pong"}]})

    receiver = messenger.FacebookReceiver(sender, dialogue_client)
    await receiver.handle_message("user123", "ping", {"foo": "bar"})

    sender.format_bot_response.assert_called_once_with({"text": "pong"})
    sender.send_message.assert_awaited_once_with("user123", {"text": "pong"})


@pytest.mark.asyncio
async def test_facebook_receiver_process_messaging_event_handles_text() -> None:
    """Text events should delegate to handle_message with proper context."""
    sender = Mock()
    dialogue_client = Mock()
    receiver = messenger.FacebookReceiver(sender, dialogue_client)
    receiver.handle_message = AsyncMock()

    event = {
        "sender": {"id": "user"},
        "timestamp": 123,
        "message": {"text": "hi"},
    }
    await receiver.process_messaging_event(event, "page1")

    receiver.handle_message.assert_awaited_once_with(
        "user",
        "hi",
        {"channel": "facebook", "page_id": "page1", "timestamp": 123},
    )


@pytest.mark.asyncio
async def test_facebook_receiver_process_messaging_event_handles_postback() -> None:
    """Postback events should flag is_postback in the context."""
    sender = Mock()
    dialogue_client = Mock()
    receiver = messenger.FacebookReceiver(sender, dialogue_client)
    receiver.handle_message = AsyncMock()

    event = {
        "sender": {"id": "user"},
        "timestamp": 999,
        "postback": {"payload": "PAYLOAD"},
    }
    await receiver.process_messaging_event(event, "page42")

    receiver.handle_message.assert_awaited_once_with(
        "user",
        "PAYLOAD",
        {
            "channel": "facebook",
            "page_id": "page42",
            "timestamp": 999,
            "is_postback": True,
        },
    )


def test_load_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuration loader should construct config from environment variables."""
    monkeypatch.setenv("FACEBOOK_PAGE_ACCESS_TOKEN", "token")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.setenv("FACEBOOK_VERIFY_TOKEN", "verify")
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_URL", "http://dm")

    config = messenger._load_config()

    assert config.page_access_token == "token"
    assert config.secret == "secret"
    assert config.verify_token == "verify"
    assert config.dialogue_manager_service_url == "http://dm"


def test_load_config_missing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing environment variables should raise RuntimeError."""
    monkeypatch.delenv("FACEBOOK_PAGE_ACCESS_TOKEN", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        messenger._load_config()

    assert "FACEBOOK_PAGE_ACCESS_TOKEN" in str(exc_info.value)


def test_get_header_value_is_case_insensitive() -> None:
    """Header lookup should ignore casing."""
    headers = {"X-Hub-Signature-256": "sig"}
    assert messenger._get_header_value(headers, "x-hub-signature-256") == "sig"
    assert messenger._get_header_value(headers, "X-HUB-SIGNATURE-256") == "sig"


def test_get_header_value_returns_none_when_missing() -> None:
    """Absent headers should yield None."""
    assert messenger._get_header_value(None, "any") is None


def test_is_valid_signature_success() -> None:
    """Valid signature should be accepted for supported algorithms."""
    secret = "secret"
    body = b"payload"
    digest = hmac.new(secret.encode("utf-8"), body, digestmod="sha256").hexdigest()
    signature = f"sha256={digest}"

    assert messenger._is_valid_signature(body, signature, secret)


def test_is_valid_signature_invalid_signature() -> None:
    """Incorrect signature values should be rejected."""
    assert not messenger._is_valid_signature(b"payload", "sha256=bad", "secret")


def test_is_valid_signature_unknown_algorithm() -> None:
    """Unsupported algorithms should be rejected."""
    assert not messenger._is_valid_signature(b"payload", "sha999=value", "secret")


def test_extract_body_plain_text() -> None:
    """Non-base64 payloads should be returned as-is."""
    assert messenger._extract_body({"body": "raw", "isBase64Encoded": False}) == "raw"


def test_extract_body_base64_decoding() -> None:
    """Base64 payloads should be decoded into strings."""
    encoded = base64.b64encode(b"decoded").decode("utf-8")
    assert messenger._extract_body({"body": encoded, "isBase64Encoded": True}) == "decoded"


def test_extract_body_invalid_base64_returns_empty() -> None:
    """Corrupt base64 should return an empty string."""
    assert messenger._extract_body({"body": "***", "isBase64Encoded": True}) == ""


def test_handle_verification_success() -> None:
    """Valid verification requests should echo the challenge."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    event = {
        "queryStringParameters": {
            "hub.mode": "subscribe",
            "hub.verify_token": "verify",
            "hub.challenge": "CHALLENGE",
        }
    }

    response = messenger._handle_verification(event, config)

    assert response["statusCode"] == 200
    assert response["body"] == "CHALLENGE"


def test_handle_verification_failure() -> None:
    """Invalid verification requests should be forbidden."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    event = {"queryStringParameters": {"hub.mode": "subscribe", "hub.verify_token": "nope"}}

    assert messenger._handle_verification(event, config)["statusCode"] == 403


@pytest.mark.asyncio
async def test_handle_webhook_payload_builds_components(monkeypatch: pytest.MonkeyPatch) -> None:
    """Webhook payload processing should instantiate components and call receiver."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    payload = {"entry": []}

    session_instance = AsyncMock()
    
    # Create a proper async context manager for ClientSession
    @asynccontextmanager
    async def mock_session_factory(*args, **kwargs):
        yield session_instance
    
    mock_aiohttp = Mock()
    mock_aiohttp.ClientSession = mock_session_factory
    monkeypatch.setattr(messenger, "aiohttp", mock_aiohttp)

    sender_instance = Mock()
    dm_client = Mock()
    receiver_instance = Mock()
    receiver_instance.process_webhook_event = AsyncMock()

    monkeypatch.setattr(messenger, "FacebookSender", Mock(return_value=sender_instance))
    monkeypatch.setattr(messenger, "RemoteDialogueManagerClient", Mock(return_value=dm_client))
    monkeypatch.setattr(messenger, "FacebookReceiver", Mock(return_value=receiver_instance))

    response = await messenger._handle_webhook_payload(payload, config)

    messenger.FacebookSender.assert_called_once_with("token", session=session_instance)
    messenger.RemoteDialogueManagerClient.assert_called_once_with("http://dm", session=session_instance)
    messenger.FacebookReceiver.assert_called_once()
    receiver_instance.process_webhook_event.assert_awaited_once_with(payload)
    assert response == {"statusCode": 200, "body": "EVENT_RECEIVED"}


def test_lambda_handler_get_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET requests should be routed to the verification handler."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    monkeypatch.setattr(messenger, "_load_config", Mock(return_value=config))

    event = {
        "httpMethod": "GET",
        "queryStringParameters": {
            "hub.mode": "subscribe",
            "hub.verify_token": "verify",
            "hub.challenge": "challenge",
        },
    }

    response = messenger.lambda_handler(event, {})

    assert response == {"statusCode": 200, "body": "challenge", "headers": {"Content-Type": "text/plain"}}


def test_lambda_handler_method_not_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsupported HTTP methods should return 405."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    monkeypatch.setattr(messenger, "_load_config", Mock(return_value=config))

    response = messenger.lambda_handler({"httpMethod": "PUT"}, {})

    assert response == {"statusCode": 405, "body": "Method Not Allowed"}


def test_lambda_handler_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requests with invalid signatures should be rejected."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    monkeypatch.setattr(messenger, "_load_config", Mock(return_value=config))
    monkeypatch.setattr(messenger, "_extract_body", Mock(return_value="payload"))
    monkeypatch.setattr(messenger, "_is_valid_signature", Mock(return_value=False))

    response = messenger.lambda_handler(
        {"httpMethod": "POST", "headers": {}},
        {},
    )

    assert response == {"statusCode": 401, "body": "Invalid signature"}


def test_lambda_handler_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed payloads should return 400."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    monkeypatch.setattr(messenger, "_load_config", Mock(return_value=config))
    monkeypatch.setattr(messenger, "_extract_body", Mock(return_value="bad"))
    monkeypatch.setattr(messenger, "_is_valid_signature", Mock(return_value=True))
    
    # Mock json.loads to raise JSONDecodeError without replacing the entire json module
    original_loads = json.loads
    def mock_loads(s):
        raise json.JSONDecodeError("msg", "bad", 0)
    
    monkeypatch.setattr(json, "loads", mock_loads)

    response = messenger.lambda_handler(
        {"httpMethod": "POST", "headers": {"x-hub-signature-256": "sig"}},
        {},
    )

    assert response == {"statusCode": 400, "body": "Invalid JSON payload"}


def test_lambda_handler_success_invokes_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid POST requests should be forwarded to the webhook handler."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    payload = {"entry": []}

    monkeypatch.setattr(messenger, "_load_config", Mock(return_value=config))
    monkeypatch.setattr(messenger, "_extract_body", Mock(return_value=json.dumps(payload)))
    monkeypatch.setattr(messenger, "_is_valid_signature", Mock(return_value=True))
    monkeypatch.setattr(messenger, "_handle_webhook_payload", AsyncMock(return_value={"statusCode": 200, "body": "ok"}))
    monkeypatch.setattr(messenger, "asyncio", Mock(run=Mock(return_value={"statusCode": 200, "body": "ok"})))

    response = messenger.lambda_handler({"httpMethod": "POST", "headers": {"x-hub-signature-256": "sig"}}, {})

    assert response == {"statusCode": 200, "body": "ok"}


def test_lambda_handler_dialogue_manager_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dialogue manager errors should translate to a 502 response."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    monkeypatch.setattr(messenger, "_load_config", Mock(return_value=config))
    monkeypatch.setattr(messenger, "_extract_body", Mock(return_value="{}"))
    monkeypatch.setattr(messenger, "_is_valid_signature", Mock(return_value=True))
    monkeypatch.setattr(messenger, "json", Mock(loads=Mock(return_value={})))
    monkeypatch.setattr(
        messenger,
        "asyncio",
        Mock(run=Mock(side_effect=messenger.DialogueManagerClientError("fail"))),
    )

    response = messenger.lambda_handler({"httpMethod": "POST", "headers": {"x-hub-signature-256": "sig"}}, {})

    assert response["statusCode"] == 502


def test_lambda_handler_http_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTPException from sending should propagate its status code."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    monkeypatch.setattr(messenger, "_load_config", Mock(return_value=config))
    monkeypatch.setattr(messenger, "_extract_body", Mock(return_value="{}"))
    monkeypatch.setattr(messenger, "_is_valid_signature", Mock(return_value=True))
    monkeypatch.setattr(messenger, "json", Mock(loads=Mock(return_value={})))
    http_exc = messenger.HTTPException(status_code=502, detail="failure")
    monkeypatch.setattr(messenger, "asyncio", Mock(run=Mock(side_effect=http_exc)))

    response = messenger.lambda_handler({"httpMethod": "POST", "headers": {"x-hub-signature-256": "sig"}}, {})

    assert response == {"statusCode": 502, "body": "failure"}


def test_lambda_handler_missing_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requests without signature headers should be rejected."""
    config = messenger.FacebookConfig("token", "secret", "verify", "http://dm")
    monkeypatch.setattr(messenger, "_load_config", Mock(return_value=config))
    monkeypatch.setattr(messenger, "_extract_body", Mock(return_value="payload"))
    # do not set _is_valid_signature so default behavior is False when signature None

    response = messenger.lambda_handler({"httpMethod": "POST", "headers": {}}, {})

    assert response == {"statusCode": 401, "body": "Invalid signature"}