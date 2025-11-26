"""
Facebook Messenger channel adapter for dialogue management.

This module implements a stateless adapter that translates Facebook Messenger
webhook events into dialogue-manager API calls and sends responses back to
Facebook Graph API.

The adapter is designed to be deployed as a Lambda function or lightweight
microservice behind API Gateway, with all state managed by the dialogue-manager
service.
"""

import hashlib
import hmac
import logging
from typing import Dict, Any, List, Optional
import aiohttp
from fastapi import HTTPException

from app.bot.dialogue_manager.models import UserMessage

logger = logging.getLogger(__name__)

FACEBOOK_API_URL = "https://graph.facebook.com/v18.0/me/messages"


class FacebookSender:
    """Handles sending messages to Facebook Messenger.
    
    Pure I/O adapter for posting messages to Facebook Graph API.
    Decoupled from dialogue logic to enable independent testing and deployment.
    """

    def __init__(self, access_token: str) -> None:
        """Initialize Facebook sender with access token.
        
        Args:
            access_token: Facebook page access token for Graph API authentication
        """
        self.access_token = access_token

    async def send_message(self, recipient_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Send a message to Facebook Messenger.
        
        Args:
            recipient_id: Facebook user ID to receive the message
            message: Message payload in Facebook format
            
        Returns:
            Response from Facebook Graph API
            
        Raises:
            HTTPException: If message delivery fails
        """
        payload = {"recipient": {"id": recipient_id}, "message": message}
        params = {"access_token": self.access_token}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                FACEBOOK_API_URL, json=payload, params=params
            ) as response:
                if response.status != 200:
                    error_data = await response.json()
                    logger.error(f"Error sending message to Facebook: {error_data}")
                    raise HTTPException(
                        status_code=500, detail="Failed to send message to Facebook"
                    )
                return await response.json()

    def format_bot_response(self, bot_message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Format bot response into Facebook message format.
        
        Args:
            bot_message: Bot message dictionary from dialogue manager
            
        Returns:
            List of formatted Facebook message payloads
        """
        messages = [bot_message]
        return messages


class FacebookReceiver:
    """Handles receiving and processing messages from Facebook Messenger.
    
    Stateless adapter that validates webhook signatures, extracts messaging events,
    and delegates to dialogue manager for NLU/state management.
    
    This class is designed to be instantiated per-request in Lambda deployments,
    with the dialogue manager client injected as a dependency.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        dialogue_manager_client: Any,
    ) -> None:
        """Initialize Facebook receiver with configuration and dialogue manager client.
        
        Args:
            config: Configuration dictionary containing:
                - page_access_token: Facebook page access token
                - secret: Webhook verification secret
            dialogue_manager_client: Client for calling dialogue manager service.
                Can be a DialogueManager instance (monolith) or HTTP client (microservice).
        """
        self.config = config
        self.dialogue_manager_client = dialogue_manager_client
        self.sender = FacebookSender(config["page_access_token"])

    def validate_hub_signature(
        self, request_payload: bytes, hub_signature_header: str
    ) -> bool:
        """Validate the request signature from Facebook.
        
        Ensures webhook requests originate from Facebook by verifying HMAC signature.
        
        Args:
            request_payload: Raw request body bytes
            hub_signature_header: X-Hub-Signature header value from Facebook
            
        Returns:
            True if signature is valid, False otherwise
        """
        try:
            hash_method, hub_signature = hub_signature_header.split("=")
            digest_module = getattr(hashlib, hash_method)
            hmac_object = hmac.new(
                bytearray(self.config["secret"], "utf8"), request_payload, digest_module
            )
            generated_hash = hmac_object.hexdigest()
            return hub_signature == generated_hash
        except Exception:
            return False

    async def handle_message(
        self, sender_id: str, message_text: str, context: Dict[str, Any]
    ) -> None:
        """Process a message through the dialogue manager and send response.
        
        Creates a UserMessage, sends it to dialogue manager, and posts responses
        back to Facebook.
        
        Args:
            sender_id: Facebook user ID
            message_text: User's message text
            context: Dialogue context with channel, page_id, timestamp, etc.
        """
        user_message = UserMessage(
            thread_id=sender_id, text=message_text, context=context or {}
        )
        
        # Call dialogue manager (direct or via HTTP client)
        new_state = await self.dialogue_manager_client.process(user_message)

        # Format and send response back to Facebook
        for message in new_state.bot_message:
            formatted_messages = self.sender.format_bot_response(message)
            for formatted_message in formatted_messages:
                await self.sender.send_message(sender_id, formatted_message)

    async def process_webhook_event(self, data: Dict[str, Any]) -> None:
        """Process a webhook event from Facebook.
        
        Iterates through all messaging events in the webhook payload and
        processes each one.
        
        Args:
            data: Webhook payload dictionary with 'entry' key containing events
        """
        # Process each entry in the webhook payload
        for entry in data.get("entry", []):
            page_id = entry.get("id")
            for messaging_event in entry.get("messaging", []):
                await self.process_messaging_event(messaging_event, page_id)

    async def process_messaging_event(
        self, event: Dict[str, Any], page_id: str
    ) -> None:
        """Process a single messaging event from Facebook.
        
        Handles text messages and postback events by extracting sender ID,
        message content, and context, then delegating to handle_message.
        
        Args:
            event: Messaging event dictionary from Facebook
            page_id: Facebook page ID for context
        """
        sender_id = event.get("sender", {}).get("id")
        if not sender_id:
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
            # Handle postback (button click, menu selection, etc.)
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