import hashlib
import hmac
import logging
from typing import Dict, Any, List, Protocol, runtime_checkable
import aiohttp
from fastapi import HTTPException

from app.bot.dialogue_manager.models import UserMessage

logger = logging.getLogger(__name__)

FACEBOOK_API_URL = "https://graph.facebook.com/v18.0/me/messages"


@runtime_checkable
class DialogueManagerClientProtocol(Protocol):
    async def process(self, user_message: UserMessage) -> Dict[str, Any]:
        """Protocol for remote dialogue-manager clients.

        Implementations should accept a UserMessage and return the new conversation
        state as a dictionary (expected to contain a 'bot_message' iterable).
        """
        ...


class DialogueManagerRemoteClient:
    """HTTP client to communicate with a remote dialogue-manager service.

    The remote service is expected to expose an endpoint that accepts a JSON
    representation of UserMessage and returns a JSON object containing the
    updated conversation state (including a 'bot_message' field).
    """

    def __init__(self, base_url: str, api_key: str | None = None, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def process(self, user_message: UserMessage) -> Dict[str, Any]:
        """Send the user message to the remote dialogue-manager and return the state.

        Args:
            user_message: UserMessage pydantic model instance.

        Returns:
            The response parsed as a dictionary from the dialogue-manager-service.

        Raises:
            HTTPException on non-200 responses from the remote service.
        """
        url = f"{self.base_url}/process"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=user_message.dict(), headers=headers, timeout=self.timeout) as resp:
                if resp.status != 200:
                    try:
                        error_data = await resp.json()
                    except Exception:
                        error_data = await resp.text()
                    logger.error("Dialogue-manager remote call failed: %s", error_data)
                    raise HTTPException(status_code=500, detail="Dialogue-manager service error")
                return await resp.json()


class FacebookSender:
    """Handles sending messages to Facebook Messenger."""

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    async def send_message(self, recipient_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Send a message to Facebook Messenger."""
        payload = {"recipient": {"id": recipient_id}, "message": message}
        params = {"access_token": self.access_token}

        async with aiohttp.ClientSession() as session:
            async with session.post(FACEBOOK_API_URL, json=payload, params=params) as response:
                if response.status != 200:
                    try:
                        error_data = await response.json()
                    except Exception:
                        error_data = await response.text()
                    logger.error(f"Error sending message to Facebook: %s", error_data)
                    raise HTTPException(status_code=500, detail="Failed to send message to Facebook")
                return await response.json()

    def format_bot_response(self, bot_message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Format bot response into Facebook message format.

        This is a simple passthrough for now; adapt as needed for cards, images, etc.
        """
        messages = [bot_message]
        return messages


def validate_hub_signature(request_payload: bytes, hub_signature_header: str, secret: str) -> bool:
    """Validate the request signature from Facebook.

    This function is written to be used by an external Lambda handler which
    performs HTTP signature verification before delegating to the receiver.
    """
    try:
        hash_method, hub_signature = hub_signature_header.split("=")
        digest_module = getattr(hashlib, hash_method)
        hmac_object = hmac.new(bytearray(secret, "utf8"), request_payload, digest_module)
        generated_hash = hmac_object.hexdigest()
        return hub_signature == generated_hash
    except Exception:
        return False


class FacebookReceiver:
    """Stateless receiver that processes Facebook webhook events and forwards
    user messages to a dialogue-manager client for processing.

    The receiver does not instantiate a dialogue manager itself; instead a
    client implementing DialogueManagerClientProtocol should be injected.
    """

    def __init__(self, config: Dict[str, Any], dialogue_client: DialogueManagerClientProtocol) -> None:
        """Initialize receiver with configuration and a dialogue-manager client.

        Args:
            config: Dict with keys including 'page_access_token'.
            dialogue_client: An object implementing process(UserMessage) -> dict.
        """
        self.config = config
        self.dialogue_client = dialogue_client
        self.sender = FacebookSender(config["page_access_token"]) 

    async def handle_message(self, sender_id: str, message_text: str, context: Dict[str, Any]) -> None:
        """Process a single user message by delegating to the dialogue-manager service
        and sending back any bot messages to Facebook.
        """
        user_message = UserMessage(thread_id=sender_id, text=message_text, context=context or {})
        new_state = await self.dialogue_client.process(user_message)

        # Format and send response back to Facebook
        bot_messages = new_state.get("bot_message", []) if isinstance(new_state, dict) else []
        for message in bot_messages:
            formatted_messages = self.sender.format_bot_response(message)
            for formatted_message in formatted_messages:
                await self.sender.send_message(sender_id, formatted_message)

    async def process_webhook_event(self, data: Dict[str, Any]) -> None:
        """Process a single webhook payload (expected to follow Facebook's format).

        Args:
            data: The parsed JSON body of the webhook request.
        """
        for entry in data.get("entry", []):
            page_id = entry.get("id")
            for messaging_event in entry.get("messaging", []):
                await self.process_messaging_event(messaging_event, page_id)

    async def process_messaging_event(self, event: Dict[str, Any], page_id: str | None) -> None:
        """Process a messaging event from Facebook and dispatch to handler.

        This method extracts relevant fields and forwards the text or postback
        payload to handle_message.
        """
        sender_id = event.get("sender", {}).get("id")
        if not sender_id:
            return

        if event.get("message") and "text" in event["message"]:
            await self.handle_message(
                sender_id,
                event["message"]["text"],
                {
                    "channel": "facebook",
                    "page_id": page_id,
                    "timestamp": event.get("timestamp"),
                },
            )
        elif event.get("postback"):
            # Handle postback payloads as user messages
            await self.handle_message(
                sender_id,
                event["postback"].get("payload", ""),
                {
                    "channel": "facebook",
                    "page_id": page_id,
                    "timestamp": event.get("timestamp"),
                    "is_postback": True,
                },
            )