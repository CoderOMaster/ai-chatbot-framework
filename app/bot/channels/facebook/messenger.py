import hashlib
import hmac
import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import aiohttp
from functools import lru_cache

logger = logging.getLogger(__name__)

FACEBOOK_API_URL = "https://graph.facebook.com/v18.0/me/messages"
RATE_LIMIT_CALLS = 100
RATE_LIMIT_WINDOW = 60  # seconds
DEDUP_WINDOW = 300  # seconds


class RateLimiter:
    """Token bucket rate limiter for Facebook API calls."""

    def __init__(self, calls: int = RATE_LIMIT_CALLS, window: int = RATE_LIMIT_WINDOW):
        self.calls = calls
        self.window = window
        self.tokens: Dict[str, List[float]] = {}

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed under rate limit."""
        now = time.time()
        if key not in self.tokens:
            self.tokens[key] = []

        # Remove old timestamps outside the window
        self.tokens[key] = [ts for ts in self.tokens[key] if now - ts < self.window]

        if len(self.tokens[key]) < self.calls:
            self.tokens[key].append(now)
            return True
        return False


class MessageDeduplicator:
    """Deduplicates messages within a time window."""

    def __init__(self, window: int = DEDUP_WINDOW):
        self.window = window
        self.seen_messages: Dict[str, datetime] = {}

    def is_duplicate(self, message_id: str) -> bool:
        """Check if message has been seen recently."""
        now = datetime.utcnow()
        if message_id in self.seen_messages:
            if now - self.seen_messages[message_id] < timedelta(seconds=self.window):
                return True
            else:
                del self.seen_messages[message_id]

        self.seen_messages[message_id] = now
        return False

    def cleanup(self) -> None:
        """Remove expired entries."""
        now = datetime.utcnow()
        expired = [
            mid
            for mid, ts in self.seen_messages.items()
            if now - ts >= timedelta(seconds=self.window)
        ]
        for mid in expired:
            del self.seen_messages[mid]


class FacebookSender:
    """Handles sending messages to Facebook Messenger."""

    def __init__(
        self,
        access_token: str,
        session: Optional[aiohttp.ClientSession] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """
        Initialize Facebook sender.

        Args:
            access_token: Facebook page access token
            session: Reusable aiohttp ClientSession
            rate_limiter: Rate limiter instance
        """
        self.access_token = access_token
        self.session = session
        self.rate_limiter = rate_limiter or RateLimiter()
        self._owns_session = session is None

    async def send_message(self, recipient_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a message to Facebook Messenger.

        Args:
            recipient_id: Facebook user ID
            message: Message payload

        Returns:
            Response from Facebook API

        Raises:
            RuntimeError: If rate limited or API error occurs
        """
        if not self.rate_limiter.is_allowed(recipient_id):
            raise RuntimeError(f"Rate limit exceeded for recipient {recipient_id}")

        payload = {"recipient": {"id": recipient_id}, "message": message}
        params = {"access_token": self.access_token}

        session = self.session or aiohttp.ClientSession()
        try:
            async with session.post(
                FACEBOOK_API_URL, json=payload, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response_data = await response.json()
                if response.status != 200:
                    logger.error(f"Error sending message to Facebook: {response_data}")
                    raise RuntimeError(f"Facebook API error: {response_data}")
                return response_data
        finally:
            if self._owns_session:
                await session.close()

    def format_bot_response(self, bot_message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Format bot response into Facebook message format.

        Args:
            bot_message: Bot message payload

        Returns:
            List of formatted messages
        """
        return [bot_message]


class FacebookReceiver:
    """Handles receiving and processing messages from Facebook Messenger."""

    def __init__(
        self,
        config: Dict[str, Any],
        dialogue_manager_url: str,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """
        Initialize Facebook receiver.

        Args:
            config: Configuration dict with 'page_access_token' and 'secret'
            dialogue_manager_url: HTTP endpoint for dialogue manager service
            session: Reusable aiohttp ClientSession
        """
        self.config = config
        self.dialogue_manager_url = dialogue_manager_url
        self.session = session
        self._owns_session = session is None
        self.rate_limiter = RateLimiter()
        self.deduplicator = MessageDeduplicator()
        self.sender = FacebookSender(
            config["page_access_token"],
            session=session,
            rate_limiter=self.rate_limiter,
        )

    def validate_hub_signature(
        self, request_payload: bytes, hub_signature_header: str
    ) -> bool:
        """
        Validate the request signature from Facebook.

        Args:
            request_payload: Raw request body
            hub_signature_header: X-Hub-Signature header value

        Returns:
            True if signature is valid
        """
        try:
            hash_method, hub_signature = hub_signature_header.split("=")
            digest_module = getattr(hashlib, hash_method)
            hmac_object = hmac.new(
                bytearray(self.config["secret"], "utf8"), request_payload, digest_module
            )
            generated_hash = hmac_object.hexdigest()
            return hub_signature == generated_hash
        except Exception as e:
            logger.warning(f"Signature validation failed: {e}")
            return False

    async def process_dialogue(
        self, sender_id: str, message_text: str, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Process message through dialogue manager service via HTTP.

        Args:
            sender_id: User ID
            message_text: Message text
            context: Additional context

        Returns:
            Dialogue state response or None on error
        """
        session = self.session or aiohttp.ClientSession()
        try:
            payload = {
                "thread_id": sender_id,
                "text": message_text,
                "context": context or {},
            }

            async with session.post(
                self.dialogue_manager_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    logger.error(f"Dialogue manager error: {response.status}")
                    return None
                return await response.json()
        except Exception as e:
            logger.error(f"Failed to call dialogue manager: {e}")
            return None
        finally:
            if self._owns_session:
                await session.close()

    async def handle_message(
        self, sender_id: str, message_text: str, context: Dict[str, Any]
    ) -> None:
        """
        Process a message and send response.

        Args:
            sender_id: Facebook user ID
            message_text: Message text
            context: Message context
        """
        new_state = await self.process_dialogue(sender_id, message_text, context)
        if not new_state:
            return

        # Format and send response back to Facebook
        bot_messages = new_state.get("bot_message", [])
        if isinstance(bot_messages, dict):
            bot_messages = [bot_messages]

        for message in bot_messages:
            try:
                formatted_messages = self.sender.format_bot_response(message)
                for formatted_message in formatted_messages:
                    await self.sender.send_message(sender_id, formatted_message)
            except RuntimeError as e:
                logger.error(f"Failed to send message: {e}")

    async def process_webhook_event(self, data: Dict[str, Any]) -> None:
        """
        Process a webhook event from Facebook.

        Args:
            data: Webhook payload
        """
        for entry in data.get("entry", []):
            page_id = entry.get("id")
            for messaging_event in entry.get("messaging", []):
                await self.process_messaging_event(messaging_event, page_id)

    async def process_messaging_event(
        self, event: Dict[str, Any], page_id: str
    ) -> None:
        """
        Process a messaging event from Facebook.

        Args:
            event: Messaging event
            page_id: Facebook page ID
        """
        sender_id = event.get("sender", {}).get("id")
        if not sender_id:
            return

        # Deduplicate messages
        message_id = event.get("message", {}).get("mid") or event.get("postback", {}).get("mid")
        if message_id and self.deduplicator.is_duplicate(message_id):
            logger.debug(f"Duplicate message detected: {message_id}")
            return

        if event.get("message") and "text" in event["message"]:
            # Handle text message
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
            # Handle postback
            await self.handle_message(
                sender_id,
                event["postback"]["payload"],
                {
                    "channel": "facebook",
                    "page_id": page_id,
                    "timestamp": event.get("timestamp"),
                    "is_postback": True,
                },
            )

    async def close(self) -> None:
        """Close session if owned by this instance."""
        if self._owns_session and self.session:
            await self.session.close()