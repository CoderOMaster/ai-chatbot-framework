"""Facebook webhook handler for Lambda deployment with async processing via SQS."""

import json
import logging
import hashlib
import hmac
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import boto3
from fastapi import APIRouter, Request, HTTPException
from app.bot.channels.facebook.messenger import FacebookReceiver

router = APIRouter(prefix="/facebook", tags=["facebook"])
logger = logging.getLogger(__name__)

# AWS clients
sqs_client = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")

# Configuration from environment
FACEBOOK_VERIFY_TOKEN = os.getenv("FACEBOOK_VERIFY_TOKEN", "")
FACEBOOK_SECRET = os.getenv("FACEBOOK_SECRET", "")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
DIALOGUE_MANAGER_URL = os.getenv("DIALOGUE_MANAGER_URL", "http://dialogue-manager:8000")
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
IDEMPOTENCY_TABLE = os.getenv("IDEMPOTENCY_TABLE", "facebook-webhook-idempotency")
IDEMPOTENCY_TTL_SECONDS = 3600  # 1 hour


class IdempotencyStore:
    """DynamoDB-backed idempotency store for webhook deduplication."""

    def __init__(self, table_name: str = IDEMPOTENCY_TABLE) -> None:
        """Initialize idempotency store.

        Args:
            table_name: DynamoDB table name for storing processed webhook IDs
        """
        self.table = dynamodb.Table(table_name)

    async def is_processed(self, webhook_id: str) -> bool:
        """Check if webhook has been processed.

        Args:
            webhook_id: Unique webhook identifier

        Returns:
            True if webhook was already processed, False otherwise
        """
        try:
            response = self.table.get_item(Key={"webhook_id": webhook_id})
            return "Item" in response
        except Exception as e:
            logger.error(f"Error checking idempotency: {e}")
            return False

    async def mark_processed(self, webhook_id: str) -> bool:
        """Mark webhook as processed.

        Args:
            webhook_id: Unique webhook identifier

        Returns:
            True if successfully marked, False otherwise
        """
        try:
            expiration_time = int(
                (datetime.now() + timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)).timestamp()
            )
            self.table.put_item(
                Item={
                    "webhook_id": webhook_id,
                    "processed_at": datetime.now().isoformat(),
                    "ttl": expiration_time,
                }
            )
            return True
        except Exception as e:
            logger.error(f"Error marking webhook as processed: {e}")
            return False


class MetricsCollector:
    """Collect and emit metrics for Facebook webhook events."""

    @staticmethod
    def record_webhook_received(event_type: str) -> None:
        """Record webhook received metric.

        Args:
            event_type: Type of webhook event (message, postback, etc.)
        """
        logger.info(
            "webhook_received",
            extra={"event_type": event_type, "timestamp": datetime.now().isoformat()},
        )

    @staticmethod
    def record_webhook_processed(event_type: str, duration_ms: float) -> None:
        """Record webhook processed metric.

        Args:
            event_type: Type of webhook event
            duration_ms: Processing duration in milliseconds
        """
        logger.info(
            "webhook_processed",
            extra={
                "event_type": event_type,
                "duration_ms": duration_ms,
                "timestamp": datetime.now().isoformat(),
            },
        )

    @staticmethod
    def record_webhook_error(event_type: str, error: str) -> None:
        """Record webhook error metric.

        Args:
            event_type: Type of webhook event
            error: Error message
        """
        logger.error(
            "webhook_error",
            extra={
                "event_type": event_type,
                "error": error,
                "timestamp": datetime.now().isoformat(),
            },
        )

    @staticmethod
    def record_duplicate_webhook(webhook_id: str) -> None:
        """Record duplicate webhook metric.

        Args:
            webhook_id: Webhook identifier
        """
        logger.info(
            "duplicate_webhook",
            extra={"webhook_id": webhook_id, "timestamp": datetime.now().isoformat()},
        )


def _validate_facebook_config() -> Dict[str, str]:
    """Validate and return Facebook configuration.

    Returns:
        Configuration dictionary

    Raises:
        ValueError: If required configuration is missing
    """
    if not FACEBOOK_VERIFY_TOKEN:
        raise ValueError("FACEBOOK_VERIFY_TOKEN not configured")
    if not FACEBOOK_SECRET:
        raise ValueError("FACEBOOK_SECRET not configured")
    if not FACEBOOK_PAGE_ACCESS_TOKEN:
        raise ValueError("FACEBOOK_PAGE_ACCESS_TOKEN not configured")
    if not SQS_QUEUE_URL:
        raise ValueError("SQS_QUEUE_URL not configured")

    return {
        "verify": FACEBOOK_VERIFY_TOKEN,
        "secret": FACEBOOK_SECRET,
        "page_access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
    }


def _validate_hub_signature(
    request_payload: bytes, hub_signature_header: str, secret: str
) -> bool:
    """Validate Facebook webhook signature.

    Args:
        request_payload: Raw request body bytes
        hub_signature_header: X-Hub-Signature header value
        secret: Facebook app secret

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        if not hub_signature_header:
            logger.warning("Missing X-Hub-Signature header")
            return False

        hash_method, hub_signature = hub_signature_header.split("=")
        digest_module = getattr(hashlib, hash_method)
        hmac_object = hmac.new(
            bytearray(secret, "utf8"), request_payload, digest_module
        )
        generated_hash = hmac_object.hexdigest()
        return hub_signature == generated_hash
    except Exception as e:
        logger.error(f"Signature validation failed: {e}")
        return False


def _generate_webhook_id(data: Dict[str, Any]) -> str:
    """Generate unique webhook identifier for idempotency.

    Args:
        data: Webhook payload

    Returns:
        Unique webhook ID hash
    """
    # Use entry ID and timestamp as unique identifier
    entry_ids = [entry.get("id") for entry in data.get("entry", [])]
    timestamp = data.get("timestamp", "")
    webhook_key = f"{':'.join(entry_ids)}:{timestamp}"
    return hashlib.sha256(webhook_key.encode()).hexdigest()


async def _enqueue_webhook_event(data: Dict[str, Any]) -> bool:
    """Enqueue webhook event to SQS for async processing.

    Args:
        data: Webhook payload

    Returns:
        True if successfully enqueued, False otherwise
    """
    try:
        sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(data),
            MessageAttributes={
                "EventType": {"StringValue": "facebook_webhook", "DataType": "String"},
                "Timestamp": {
                    "StringValue": datetime.now().isoformat(),
                    "DataType": "String",
                },
            },
        )
        return True
    except Exception as e:
        logger.error(f"Error enqueuing webhook to SQS: {e}")
        return False


@router.get("/webhook")
async def verify_webhook(request: Request) -> int:
    """Handle Facebook webhook verification (GET request).

    Args:
        request: FastAPI request object

    Returns:
        Challenge value as integer

    Raises:
        HTTPException: If verification fails
    """
    try:
        config = _validate_facebook_config()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise HTTPException(status_code=500, detail="Server configuration error")

    hub_mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if hub_mode and token:
        if hub_mode == "subscribe" and token == config["verify"]:
            logger.info("Facebook webhook verified successfully")
            return int(challenge)
        logger.warning(f"Invalid verification token: {token}")
        raise HTTPException(status_code=403, detail="Invalid verification token")

    logger.warning("Missing webhook verification parameters")
    raise HTTPException(status_code=400, detail="Invalid request parameters")


@router.post("/webhook")
async def webhook(request: Request) -> Dict[str, bool]:
    """Handle incoming Facebook webhook events (POST request).

    Validates signature, checks for duplicates, and enqueues to SQS for async processing.

    Args:
        request: FastAPI request object

    Returns:
        Success response dictionary

    Raises:
        HTTPException: If validation or processing fails
    """
    start_time = datetime.now()

    try:
        config = _validate_facebook_config()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise HTTPException(status_code=500, detail="Server configuration error")

    # Get raw body for signature validation
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature", "")

    # Validate signature
    if not _validate_hub_signature(body, signature, config["secret"]):
        logger.warning("Invalid webhook signature")
        MetricsCollector.record_webhook_error("webhook", "invalid_signature")
        raise HTTPException(status_code=403, detail="Invalid request signature")

    try:
        data = await request.json()
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook: {e}")
        MetricsCollector.record_webhook_error("webhook", "invalid_json")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Generate webhook ID for idempotency
    webhook_id = _generate_webhook_id(data)

    # Check for duplicates
    idempotency_store = IdempotencyStore()
    if await idempotency_store.is_processed(webhook_id):
        logger.info(f"Duplicate webhook detected: {webhook_id}")
        MetricsCollector.record_duplicate_webhook(webhook_id)
        # Return success to acknowledge to Facebook
        return {"success": True}

    # Mark as processed
    await idempotency_store.mark_processed(webhook_id)

    # Record metrics
    event_type = "webhook"
    if data.get("entry"):
        for entry in data["entry"]:
            if entry.get("messaging"):
                event_type = "messaging"
                break

    MetricsCollector.record_webhook_received(event_type)

    # Enqueue to SQS for async processing
    if not await _enqueue_webhook_event(data):
        logger.error("Failed to enqueue webhook event")
        MetricsCollector.record_webhook_error(event_type, "sqs_enqueue_failed")
        # Still return 202 to acknowledge to Facebook
        # The event will be retried by Facebook if we don't acknowledge

    # Calculate processing time
    duration_ms = (datetime.now() - start_time).total_seconds() * 1000
    MetricsCollector.record_webhook_processed(event_type, duration_ms)

    # Return 202 Accepted to indicate async processing
    return {"success": True}


@router.post("/process-event")
async def process_webhook_event_handler(request: Request) -> Dict[str, bool]:
    """Process webhook event from SQS (internal endpoint for Lambda worker).

    This endpoint is called by a separate Lambda worker that processes SQS messages.

    Args:
        request: FastAPI request object containing webhook data

    Returns:
        Success response dictionary

    Raises:
        HTTPException: If processing fails
    """
    try:
        config = _validate_facebook_config()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise HTTPException(status_code=500, detail="Server configuration error")

    try:
        data = await request.json()
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in event processing: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        # Initialize Facebook receiver with HTTP dialogue manager URL
        facebook = FacebookReceiver(
            config=config, dialogue_manager_url=DIALOGUE_MANAGER_URL
        )

        # Process the webhook event
        await facebook.process_webhook_event(data)

        logger.info("Webhook event processed successfully")
        return {"success": True}

    except Exception as e:
        logger.error(f"Error processing webhook event: {e}", exc_info=True)
        MetricsCollector.record_webhook_error("event_processing", str(e))
        raise HTTPException(status_code=500, detail="Error processing webhook event")