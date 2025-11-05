import os
import json
import logging
from typing import Any, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.common.webhooks import parse_lambda_event_body

logger = logging.getLogger(__name__)

FORWARDING_ENDPOINT = os.getenv("FORWARDING_ENDPOINT")
FORWARDING_SQS_URL = os.getenv("FORWARDING_SQS_URL")


def _post_with_retries(url: str, payload: Dict[str, Any], timeout: int = 5):
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    resp = session.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp


def _push_to_sqs(sqs_url: str, message_body: Dict[str, Any]):
    import boto3
    import json as _json
    client = boto3.client("sqs")
    try:
        return client.send_message(QueueUrl=sqs_url, MessageBody=_json.dumps(message_body))
    except Exception:
        logger.exception("Failed to push message to SQS")
        raise


def handler(event: Dict[str, Any], context: Any):
    """
    Generic REST webhook lambda.

    Expects the body to be JSON mapping to the internal UserMessage shape. If not, forwards raw payload.
    """
    try:
        body_bytes, headers = parse_lambda_event_body(event)
    except ValueError as e:
        logger.error("Failed to parse event body: %s", e)
        return {"statusCode": 400, "body": "Invalid request"}

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        logger.exception("Invalid JSON payload")
        return {"statusCode": 400, "body": "Invalid JSON"}

    # Optionally map to canonical UserMessage if keys present
    canonical = None
    if all(k in payload for k in ("thread_id", "text")):
        canonical = {"thread_id": payload.get("thread_id"), "text": payload.get("text"), "context": payload.get("context")}

    final_payload = canonical or payload

    if FORWARDING_SQS_URL:
        try:
            _push_to_sqs(FORWARDING_SQS_URL, final_payload)
            return {"statusCode": 200, "body": json.dumps({"success": True})}
        except Exception:
            return {"statusCode": 502, "body": "Failed to forward to SQS"}

    if FORWARDING_ENDPOINT:
        try:
            _post_with_retries(FORWARDING_ENDPOINT, final_payload)
            return {"statusCode": 200, "body": json.dumps({"success": True})}
        except Exception:
            logger.exception("Failed to forward to endpoint")
            return {"statusCode": 502, "body": "Failed to forward to endpoint"}

    logger.error("No forwarding configuration; dropping message")
    return {"statusCode": 500, "body": "No forwarding configured"}