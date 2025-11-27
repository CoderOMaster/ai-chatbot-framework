"""Facebook Messenger channel adapter with retry logic, rate limiting, and message deduplication."""

import hashlib
import hmac
import logging
import asyncio
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from collections import deque
import aiohttp
from fastapi import HTTPException

from app.bot.dialogue_manager.models import UserMessage

logger = logging.getLogger(__name__)

FACEBOOK_API_URL = "https://graph.facebook.com/v18.0/me/messages"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 100
MESSAGE_DEDUP_WINDOW_SECONDS = 5


class RateLimiter:
    """Token bucket rate limiter for Facebook API requests."""

    def __init__(
        self,
        max_requests: int = RATE_LIMIT_MAX_REQUESTS,
        window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.request_times: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire permission to make a request, waiting if necessary."""
        async with self._lock:
            now = datetime.now()
            cutoff = now - timedelta(seconds=self.window_seconds)

            # Remove old requests outside the window
            while self.request_times and self.request_times[0] < cutoff:
                self.request_times.popleft()

            # If at limit, wait
            if len(self.request_times) >= self.max_requests:
                sleep_time = (
                    self.request_times[0] - cutoff
                ).total_seconds() + 0.1
                await asyncio.sleep(sleep_time)
                await self.acquire()
            else:
                self.request_times.append(now)


class MessageDeduplicator:
    """Deduplicates messages within a time window to prevent duplicate processing."""

    def __init__(self, window_seconds: int = MESSAGE_DEDUP_WINDOW_SECONDS) -> None:
        """Initialize deduplicator.

        Args:
            window_seconds: Time window for deduplication
        """
        self.window_seconds = window_seconds
        self.seen_messages: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    def _generate_message_id(
        self, sender_id: str, message_text: str, timestamp: int
    ) -> str:
        """Generate unique message identifier.

        Args:
            sender_id: Facebook sender ID
            message_text: Message text content
            timestamp: Message timestamp

        Returns:
            Unique message hash
        """
        message_key = f"{sender_id}:{message_text}:{timestamp}"
        return hashlib.sha256(message_key.encode()).hexdigest()

    async def is_duplicate(
        self, sender_id: str, message_text: str, timestamp: int
    ) -> bool:
        """Check if message is a duplicate.

        Args:
            sender_id: Facebook sender ID
            message_text: Message text content
            timestamp: Message timestamp

        Returns:
            True if message is a duplicate
        """
        async with self._lock:
            message_id = self._generate_message_id(sender_id, message_text, timestamp)
            now = datetime.now()
            cutoff = now - timedelta(seconds=self.window_seconds)

            # Clean up old entries
            expired_ids = [
                mid
                for mid, msg_time in self.seen_messages.items()
                if msg_time < cutoff
            ]
            for mid in expired_ids:
                del self.seen_messages[mid]

            # Check if duplicate
            if message_id in self.seen_messages:
                return True

            # Record message
            self.seen_messages[message_id] = now
            return False


class MessageQueue:
    """Reliable message queue for Facebook messages with retry logic."""

    def __init__(self, max_retries: int = MAX_RETRIES) -> None:
        """Initialize message queue.

        Args:
            max_retries: Maximum retry attempts per message
        """
        self.max_retries = max_retries
        self.queue: asyncio.Queue = asyncio.Queue()
        self._lock = asyncio.Lock()

    async def enqueue(self, message: Dict[str, Any]) -> None:
        """Add message to queue.

        Args:
            message: Message dictionary to queue
        """
        await self.queue.put({"data": message, "retries": 0})

    async def dequeue(self) -> Optional[Dict[str, Any]]:
        """Remove and return next message from queue.

        Returns:
            Message dictionary or None if queue empty
        """
        try:
            return self.queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def requeue(self, message: Dict[str, Any]) -> bool:
        """Requeue message if retries remain.

        Args:
            message: Message to requeue

        Returns:
            True if requeued, False if max retries exceeded
        """
        async with self._lock:
            if message["retries"] < self.max_retries:
                message["retries"] += 1
                await self.queue.put(message)
                return True
            return False


class FacebookSender:
    """Handles sending messages to Facebook Messenger with retry and rate limiting."""

    def __init__(
        self,
        access_token: str,
        rate_limiter: Optional[RateLimiter] = None,
        message_queue: Optional[MessageQueue] = None,
    ) -> None:
        """Initialize Facebook sender.

        Args:
            access_token: Facebook page access token
            rate_limiter: Optional rate limiter instance
            message_queue: Optional message queue instance
        """
        self.access_token = access_token
        self.rate_limiter = rate_limiter or RateLimiter()
        self.message_queue = message_queue or MessageQueue()

    async def send_message(
        self, recipient_id: str, message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send a message to Facebook Messenger with retry logic.

        Args:
            recipient_id: Facebook recipient ID
            message: Message dictionary

        Returns:
            API response dictionary

        Raises:
            HTTPException: If message sending fails after retries
        """
        payload = {"recipient": {"id": recipient_id}, "message": message}
        params = {"access_token": self.access_token}

        for attempt in range(MAX_RETRIES):
            try:
                # Apply rate limiting
                await self.rate_limiter.acquire()

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        FACEBOOK_API_URL, json=payload, params=params, timeout=10
                    ) as response:
                        if response.status == 200:
                            return await response.json()

                        error_data = await response.json()

                        # Handle rate limiting
                        if response.status == 429:
                            retry_after = int(
                                response.headers.get("Retry-After", RETRY_BACKOFF_SECONDS)
                            )
                            logger.warning(
                                f"Rate limited. Waiting {retry_after} seconds"
                            )
                            await asyncio.sleep(retry_after)
                            continue

                        # Handle retryable errors
                        if response.status >= 500 or response.status == 408:
                            if attempt < MAX_RETRIES - 1:
                                wait_time = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                                logger.warning(
                                    f"Retryable error {response.status}. "
                                    f"Retrying in {wait_time}s (attempt {attempt + 1}/{MAX_RETRIES})"
                                )
                                await asyncio.sleep(wait_time)
                                continue

                        logger.error(
                            f"Error sending message to Facebook: {error_data}",
                            extra={"status": response.status, "error": error_data},
                        )
                        raise HTTPException(
                            status_code=500,
                            detail="Failed to send message to Facebook",
                        )

            except asyncio.TimeoutError:
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                    logger.warning(
                        f"Request timeout. Retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.error("Request timeout after all retries")
                raise HTTPException(status_code=504, detail="Request timeout")

            except aiohttp.ClientError as e:
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                    logger.warning(
                        f"Client error: {e}. Retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"Client error after all retries: {e}")
                raise HTTPException(status_code=500, detail="Failed to send message")

        raise HTTPException(
            status_code=500, detail="Failed to send message after all retries"
        )

    def format_bot_response(self, bot_message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Format bot response into Facebook message format.

        Args:
            bot_message: Bot message dictionary

        Returns:
            List of formatted Facebook messages
        """
        messages = [bot_message]
        return messages


class FacebookReceiver:
    """Handles receiving and processing messages from Facebook Messenger."""

    def __init__(
        self,
        config: Dict[str, Any],
        dialogue_manager_url: str,
        rate_limiter: Optional[RateLimiter] = None,
        message_queue: Optional[MessageQueue] = None,
    ) -> None:
        """Initialize Facebook receiver.

        Args:
            config: Configuration dictionary with page_access_token and secret
            dialogue_manager_url: URL to dialogue manager service
            rate_limiter: Optional rate limiter instance
            message_queue: Optional message queue instance
        """
        self.config = config
        self.dialogue_manager_url = dialogue_manager_url
        self.sender = FacebookSender(
            config["page_access_token"],
            rate_limiter=rate_limiter,
            message_queue=message_queue,
        )
        self.deduplicator = MessageDeduplicator()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.message_queue = message_queue or MessageQueue()

    def validate_hub_signature(
        self, request_payload: bytes, hub_signature_header: str
    ) -> bool:
        """Validate the request signature from Facebook.

        Args:
            request_payload: Raw request body bytes
            hub_signature_header: X-Hub-Signature header value

        Returns:
            True if signature is valid, False otherwise
        """
        try:
            hash_method, hub_signature = hub_signature_header.split("=")
            digest_module = getattr(hashlib, hash_method)
            hmac_object = hmac.new(
                bytearray(self.config["secret"], "utf8"),
                request_payload,
                digest_module,
            )
            generated_hash = hmac_object.hexdigest()
            return hub_signature == generated_hash
        except Exception as e:
            logger.error(f"Signature validation failed: {e}")
            return False

    async def handle_message(
        self, sender_id: str, message_text: str, context: Dict[str, Any]
    ) -> None:
        """Process a message through the dialogue manager and send response.

        Args:
            sender_id: Facebook sender ID
            message_text: Message text content
            context: Message context dictionary
        """
        try:
            user_message = UserMessage(
                thread_id=sender_id, text=message_text, context=context or {}
            )

            # Call dialogue manager via HTTP
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.dialogue_manager_url}/process",
                    json=user_message.to_dict(),
                    timeout=30,
                ) as response:
                    if response.status != 200:
                        error_data = await response.json()
                        logger.error(
                            f"Dialogue manager error: {error_data}",
                            extra={"status": response.status},
                        )
                        return

                    result = await response.json()
                    bot_messages = result.get("bot_message", [])

                    # Send response messages back to Facebook
                    for message in bot_messages:
                        formatted_messages = self.sender.format_bot_response(message)
                        for formatted_message in formatted_messages:
                            await self.sender.send_message(sender_id, formatted_message)

        except asyncio.TimeoutError:
            logger.error("Dialogue manager request timeout")
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)

    async def process_webhook_event(self, data: Dict[str, Any]) -> None:
        """Process a webhook event from Facebook.

        Args:
            data: Webhook payload dictionary
        """
        # Process each entry in the webhook payload
        for entry in data.get("entry", []):
            page_id = entry.get("id")
            for messaging_event in entry.get("messaging", []):
                await self.process_messaging_event(messaging_event, page_id)

    async def process_messaging_event(
        self, event: Dict[str, Any], page_id: str
    ) -> None:
        """Process a messaging event from Facebook.

        Args:
            event: Messaging event dictionary
            page_id: Facebook page ID
        """
        sender_id = event.get("sender", {}).get("id")
        if not sender_id:
            return

        timestamp = event.get("timestamp", 0)

        if event.get("message") and "text" in event["message"]:
            # Handle text message
            message_text = event["message"]["text"]

            # Check for duplicates
            if await self.deduplicator.is_duplicate(sender_id, message_text, timestamp):
                logger.debug(f"Duplicate message detected from {sender_id}")
                return

            await self.handle_message(
                sender_id,
                message_text,
                {
                    "channel": "facebook",
                    "page_id": page_id,
                    "timestamp": timestamp,
                },
            )

        elif event.get("postback"):
            # Handle postback
            payload = event["postback"]["payload"]

            # Check for duplicates
            if await self.deduplicator.is_duplicate(sender_id, payload, timestamp):
                logger.debug(f"Duplicate postback detected from {sender_id}")
                return

            await self.handle_message(
                sender_id,
                payload,
                {
                    "channel": "facebook",
                    "page_id": page_id,
                    "timestamp": timestamp,
                    "is_postback": True,
                },
            )