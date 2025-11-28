import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import aiohttp
from fastapi import HTTPException

from app.bot.dialogue_manager.models import UserMessage

logger = logging.getLogger(__name__)

FACEBOOK_API_URL = "https://graph.facebook.com/v18.0/me/messages"
HUB_SIGNATURE_HEADER = "x-hub-signature-256"
LEGACY_SIGNATURE_HEADER = "x-hub-signature"


class DialogueManagerClientError(Exception):
    """Signals that the dialogue manager service returned an unexpected result."""


class DialogueManagerClient(Protocol):
    """Defines the contract that any dialogue manager client must satisfy."""

    async def process(self, user_message: UserMessage) -> Dict[str, Any]:
        """Send the user message to a dialogue manager and return the resulting state."""


class RemoteDialogueManagerClient:
    """HTTP client that forwards messages to a remote dialogue-manager-service."""

    def __init__(self, service_url: str, session: aiohttp.ClientSession) -> None:
        self._service_url = service_url
        self._session = session

    async def process(self, user_message: UserMessage) -> Dict[str, Any]:
        """Forward the serialized user message to the dialogue manager service."""
        payload = user_message.to_dict()
        try:
            async with self._session.post(self._service_url, json=payload) as response:
                if response.status != 200:
                    details = await response.text()
                    logger.error(
                        "Dialogue manager service returned %s: %s",
                        response.status,
                        details,
                    )
                    raise DialogueManagerClientError(
                        "Dialogue manager service rejected the request"
                    )
                return await response.json()
        except aiohttp.ClientError as exc:  # pragma: no cover - network issues
            logger.error("Failed to reach dialogue manager service: %s", exc)
            raise DialogueManagerClientError(
                "Unable to communicate with the dialogue manager service"
            )


class FacebookSender:
    """Handles sending messages to Facebook Messenger."""

    def __init__(
        self, access_token: str, session: Optional[aiohttp.ClientSession] = None
    ) -> None:
        self.access_token = access_token
        self._session = session

    async def send_message(self, recipient_id: str, message: Dict[str, Any]) -> None:
        """Send a message to Facebook Messenger."""

        payload = {"recipient": {"id": recipient_id}, "message": message}
        params = {"access_token": self.access_token}

        async def _send(session: aiohttp.ClientSession) -> None:
            async with session.post(FACEBOOK_API_URL, json=payload, params=params) as response:
                if response.status != 200:
                    error_data = await response.json()
                    logger.error("Error sending message to Facebook: %s", error_data)
                    raise HTTPException(
                        status_code=500, detail="Failed to send message to Facebook"
                    )

        if self._session:
            await _send(self._session)
        else:
            async with aiohttp.ClientSession() as tmp_session:
                await _send(tmp_session)

    def format_bot_response(self, bot_message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Format bot response into Facebook message format."""

        return [bot_message]


class FacebookReceiver:
    """Handles receiving and processing messages from Facebook Messenger."""

    def __init__(
        self,
        sender: FacebookSender,
        dialogue_manager_client: DialogueManagerClient,
    ) -> None:
        self.sender = sender
        self.dialogue_manager_client = dialogue_manager_client

    async def handle_message(
        self, sender_id: str, message_text: str, context: Dict[str, Any]
    ) -> None:
        """Process a message through the dialogue manager client and send response."""

        user_message = UserMessage(
            thread_id=sender_id, text=message_text, context=context or {}
        )
        new_state = await self.dialogue_manager_client.process(user_message)

        for bot_message in new_state.get("bot_message", []):
            formatted_messages = self.sender.format_bot_response(bot_message)
            for formatted_message in formatted_messages:
                await self.sender.send_message(sender_id, formatted_message)

    async def process_webhook_event(self, data: Dict[str, Any]) -> None:
        """Process a single webhook event payload from Facebook."""

        for entry in data.get("entry", []):
            page_id = entry.get("id")
            for messaging_event in entry.get("messaging", []):
                await self.process_messaging_event(messaging_event, page_id)

    async def process_messaging_event(
        self, event: Dict[str, Any], page_id: Optional[str]
    ) -> None:
        """Process an individual messaging event from Facebook."""

        sender_id = event.get("sender", {}).get("id")
        if not sender_id:
            return

        timestamp = event.get("timestamp")
        base_context: Dict[str, Any] = {
            "channel": "facebook",
            "page_id": page_id,
            "timestamp": timestamp,
        }

        if event.get("message") and "text" in event["message"]:
            await self.handle_message(
                sender_id,
                event["message"]["text"],
                base_context,
            )
        elif event.get("postback"):
            await self.handle_message(
                sender_id,
                event["postback"].get("payload", ""),
                {
                    **base_context,
                    "is_postback": True,
                },
            )


@dataclass(frozen=True)
class FacebookConfig:
    """Holds configuration values required by the Facebook webhook handler."""

    page_access_token: str
    secret: str
    verify_token: str
    dialogue_manager_service_url: str


def _load_config() -> FacebookConfig:
    """Read the required configuration from environment variables."""

    try:
        return FacebookConfig(
            page_access_token=os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"],
            secret=os.environ["FACEBOOK_APP_SECRET"],
            verify_token=os.environ["FACEBOOK_VERIFY_TOKEN"],
            dialogue_manager_service_url=os.environ[
                "DIALOGUE_MANAGER_SERVICE_URL"
            ],
        )
    except KeyError as exc:
        missing_var = exc.args[0]
        logger.error("Missing required environment variable: %s", missing_var)
        raise RuntimeError(f"Environment variable {missing_var} is required")


def _get_header_value(headers: Optional[Dict[str, Any]], header_name: str) -> Optional[str]:
    """Retrieve a header value ignoring case sensitivity."""

    if not headers:
        return None
    for key, value in headers.items():
        if key.lower() == header_name.lower():
            return value
    return None


def _is_valid_signature(body: bytes, header_signature: Optional[str], secret: str) -> bool:
    """Validate the incoming webhook signature against the configured app secret."""

    if not header_signature:
        return False

    try:
        algorithm, signature = header_signature.split("=", 1)
    except ValueError:
        return False

    digest_module = getattr(hashlib, algorithm, None)
    if not digest_module:
        return False

    computed_hash = hmac.new(secret.encode("utf-8"), body, digest_module).hexdigest()
    return hmac.compare_digest(signature, computed_hash)


def _extract_body(event: Dict[str, Any]) -> str:
    """Extract the textual body from the Lambda event, decoding if necessary."""

    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            decoded = base64.b64decode(body)
            return decoded.decode("utf-8")
        except (base64.binascii.Error, UnicodeDecodeError):
            return ""
    return body


def _handle_verification(event: Dict[str, Any], config: FacebookConfig) -> Dict[str, Any]:
    """Respond to Facebook's webhook verification challenge."""

    params = event.get("queryStringParameters") or {}
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == config.verify_token and challenge:
        return {
            "statusCode": 200,
            "body": challenge,
            "headers": {"Content-Type": "text/plain"},
        }

    return {"statusCode": 403, "body": "Forbidden"}


async def _handle_webhook_payload(
    payload: Dict[str, Any], config: FacebookConfig
) -> Dict[str, Any]:
    """Process the webhook payload by forwarding each message to the dialogue manager."""

    async with aiohttp.ClientSession() as session:
        sender = FacebookSender(config.page_access_token, session=session)
        dialogue_client = RemoteDialogueManagerClient(
            config.dialogue_manager_service_url, session=session
        )
        receiver = FacebookReceiver(sender, dialogue_client)
        await receiver.process_webhook_event(payload)
    return {"statusCode": 200, "body": "EVENT_RECEIVED"}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda entry point for handling Facebook Messenger webhooks."""

    config = _load_config()
    method = (event.get("httpMethod") or "POST").upper()

    if method == "GET":
        return _handle_verification(event, config)

    if method != "POST":
        return {"statusCode": 405, "body": "Method Not Allowed"}

    body = _extract_body(event)
    headers = event.get("headers") or {}
    signature = (
        _get_header_value(headers, HUB_SIGNATURE_HEADER)
        or _get_header_value(headers, LEGACY_SIGNATURE_HEADER)
    )

    if not _is_valid_signature(body.encode("utf-8"), signature, config.secret):
        return {"statusCode": 401, "body": "Invalid signature"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "Invalid JSON payload"}

    try:
        return asyncio.run(_handle_webhook_payload(payload, config))
    except DialogueManagerClientError as exc:  # pragma: no cover
        logger.error("Dialogue manager client failed: %s", exc, exc_info=exc)
        return {
            "statusCode": 502,
            "body": "Dialogue manager service unavailable",
        }
    except HTTPException as exc:
        logger.error("Failed to send reply to Facebook: %s", exc, exc_info=exc)
        return {"statusCode": exc.status_code, "body": exc.detail}
    except Exception as exc:  # pragma: no cover
        logger.error("Unhandled exception while handling webhook", exc_info=exc)
        return {"statusCode": 500, "body": "Internal server error"}