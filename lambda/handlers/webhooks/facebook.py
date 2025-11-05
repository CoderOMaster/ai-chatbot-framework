import os
import json
import logging
import hmac
import hashlib
from typing import Any, Dict

import requests
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.common.webhooks import verify_facebook_signature, parse_lambda_event_body

logger = logging.getLogger(__name__)

# Environment variables
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
FORWARDING_ENDPOINT = os.getenv("FORWARDING_ENDPOINT")
FORWARDING_SQS_URL = os.getenv("FORWARDING_SQS_URL")

# SQS client (lazy)
_sqs_client = None

def get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs")
    return _sqs_client


def _post_with_retries(url: str, payload: Dict[str, Any], timeout: int = 5):
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    resp = session.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp


def _push_to_sqs(sqs_url: str, message_body: Dict[str, Any]):
    client = get_sqs_client()
    try:
        return client.send_message(QueueUrl=sqs_url, MessageBody=json.dumps(message_body))
    except (BotoCoreError, ClientError) as e:
        logger.exception("Failed to push message to SQS: %s", str(e))
        raise


def handler(event: Dict[str, Any], context: Any):
    """
    AWS Lambda handler for Facebook webhooks.
    Validates request signature and forwards payload to configured endpoint or SQS.
    """
    try:
        body_bytes, headers = parse_lambda_event_body(event)
    except ValueError as e:
        logger.error("Failed to parse event body: %s", e)
        return {"statusCode": 400, "body": "Invalid request"}

    signature = headers.get("X-Hub-Signature", "")

    if not FACEBOOK_APP_SECRET:
        logger.warning("FACEBOOK_APP_SECRET not set; skipping signature verification")
    else:
        if not verify_facebook_signature(body_bytes, signature, FACEBOOK_APP_SECRET):
            logger.warning("Invalid facebook signature")
            return {"statusCode": 403, "body": "Invalid signature"}

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        logger.exception("Invalid JSON payload")
        return {"statusCode": 400, "body": "Invalid JSON"}

    # Prefer SQS for async processing if configured
    if FORWARDING_SQS_URL:
        try:
            _push_to_sqs(FORWARDING_SQS_URL, payload)
            return {"statusCode": 200, "body": json.dumps({"success": True})}
        except Exception:
            return {"statusCode": 502, "body": "Failed to forward to SQS"}

    if FORWARDING_ENDPOINT:
        try:
            _post_with_retries(FORWARDING_ENDPOINT, payload)
            return {"statusCode": 200, "body": json.dumps({"success": True})}
        except Exception:
            logger.exception("Failed to forward to endpoint")
            return {"statusCode": 502, "body": "Failed to forward to endpoint"}

    logger.error("No forwarding configuration; dropping message")
    return {"statusCode": 500, "body": "No forwarding configured"}