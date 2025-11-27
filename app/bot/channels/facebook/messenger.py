import hashlib
import hmac
import logging
from typing import Dict, Any, List, Optional
import aiohttp
from fastapi import HTTPException

from app.bot.dialogue_manager.models import UserMessage
from app.bot.dialogue_manager.utils import make_context
from typing import Any as AnyType

logger = logging.getLogger(__name__)

FACEBOOK_API_URL = "https://graph.facebook.com/v18.0/me/messages"

# Module-level shared aiohttp session reused across the process. Created lazily.
_shared_session: Optional[aiohttp.ClientSession] = None


async def get_shared_session() -> aiohttp.ClientSession:
    """Return a lazily-initialized shared aiohttp.ClientSession for the process.

    This avoids creating a new TCP connection pool per request and is safe to use
    by all callers in this module. The session is not closed here; the application
    should arrange graceful shutdown if needed.
    """
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        _shared_session = aiohttp.ClientSession()
    return _shared_session


def validate_hub_signature(request_payload: bytes, hub_signature_header: str, secret: str) -> bool:
    """Validate Facebook webhook hub.signature header.

    Args:
        request_payload: Raw request body bytes.
        hub_signature_header: Value of the 'X-Hub-Signature' header (e.g. 'sha1=...').
        secret: App secret shared with Facebook.

    Returns:
        True if signature matches, False otherwise.
    """
    try:
        hash_method, hub_signature = hub_signature_header.split("=")
        digest_module = getattr(hashlib, hash_method)
        hmac_object = hmac.new(bytearray(secret, "utf8"), request_payload, digest_module)
        generated_hash = hmac_object.hexdigest()
        return hub_signature == generated_hash
    except Exception:
        return False


class FacebookSender:
    """Handles sending messages to Facebook Messenger.

    The sender reuses a shared aiohttp session by default but accepts an
    injected session for testing.
    """

    def __init__(self, access_token: str, session: Optional[aiohttp.ClientSession] = None) -> None:
        self.access_token = access_token
        self._injected_session = session

    async def _get_session(self) -> aiohttp.ClientSession:
        return self._injected_session or await get_shared_session()

    async def send_message(self, recipient_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Send a single message to Facebook Messenger using a shared session.

        Kept for backwards compatibility; prefer send_messages for batching.
        """
        session = await self._get_session()
        payload = {"recipient": {"id": recipient_id}, "message": message}
        params = {"access_token": self.access_token}

        async with session.post(FACEBOOK_API_URL, json=payload, params=params) as response:
            if response.status != 200:
                error_data = await response.json()
                logger.error("Error sending message to Facebook: %s", error_data)
                raise HTTPException(status_code=500, detail="Failed to send message to Facebook")
            return await response.json()

    async def send_messages(self, recipient_id: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send multiple messages in order to the recipient.

        Messages are sent sequentially to preserve order (useful for multi-turn
        replies). Returns the list of responses from Facebook.
        """
        results: List[Dict[str, Any]] = []
        for message in messages:
            res = await self.send_message(recipient_id, message)
            results.append(res)
        return results

    def format_bot_response(self, bot_message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Format internal bot message structure into Facebook message payloads.

        The dialogue manager produces bot_message entries like {'text': '...'}.
        Keep this flexible so richer message types can be supported in future.
        """
        # Currently we only handle text messages; preserve incoming structure.
        return [bot_message]


class FacebookReceiver:
    """Handles receiving and processing messages from Facebook Messenger.

    The receiver accepts a dialogue_manager via dependency injection. Any object
    providing an async 'process(user_message: UserMessage) -> State' method is
    acceptable which makes testing easier.
    """

    def __init__(self, config: Dict[str, Any], dialogue_manager: AnyType, sender: Optional[FacebookSender] = None) -> None:
        """Initialize the receiver.

        Args:
            config: Dict containing 'page_access_token' and 'secret'.
            dialogue_manager: Injected dialogue manager implementing process(...).
            sender: Optional injected FacebookSender instance for testing.
        """
        self.config = config
        self.dialogue_manager = dialogue_manager
        self.sender = sender or FacebookSender(config["page_access_token"]) 

    def validate_hub_signature(self, request_payload: bytes, hub_signature_header: str) -> bool:
        """Instance wrapper around the shared validate_hub_signature utility."""
        return validate_hub_signature(request_payload, hub_signature_header, self.config.get("secret", ""))

    async def handle_message(self, sender_id: str, message_text: str, context: Dict[str, Any]) -> None:
        """Process a message through the dialogue manager and send response(s).

        Constructs a UserMessage value object and passes it to the injected
        dialogue_manager. Responses returned in the state are formatted and sent
        back to Facebook in a batch to preserve order for multi-turn replies.
        """
        user_message = UserMessage(thread_id=sender_id, text=message_text, context=context or {})
        new_state = await self.dialogue_manager.process(user_message)

        # Collect formatted messages for batch send
        batch: List[Dict[str, Any]] = []
        for message in new_state.bot_message:
            formatted_messages = self.sender.format_bot_response(message)
            batch.extend(formatted_messages)

        if batch:
            await self.sender.send_messages(sender_id, batch)

    async def process_webhook_event(self, data: Dict[str, Any]) -> None:
        """Process a webhook payload from Facebook.

        This iterates over entries and delegates to process_messaging_event for each
        messaging event.
        """
        for entry in data.get("entry", []):
            page_id = entry.get("id")
            for messaging_event in entry.get("messaging", []):
                await self.process_messaging_event(messaging_event, page_id)

    async def process_messaging_event(self, event: Dict[str, Any], page_id: str) -> None:
        """Process a single messaging event from Facebook and dispatch to handler.

        Builds a context using the dialogue manager helpers to avoid manual dict
        construction.
        """
        sender_id = event.get("sender", {}).get("id")
        if not sender_id:
            return

        base_context = make_context(channel="facebook", page_id=page_id, timestamp=event.get("timestamp"))

        if event.get("message") and "text" in event["message"]:
            # Handle text message
            await self.handle_message(sender_id, event["message"]["text"], base_context)
        elif event.get("postback"):
            # Handle postback payloads as messages
            ctx = make_context(**base_context, is_postback=True)
            await self.handle_message(sender_id, event["postback"]["payload"], ctx)