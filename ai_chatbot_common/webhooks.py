import hmac
import hashlib
import json
import os
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


def _const_time_compare(val1: str, val2: str) -> bool:
    if len(val1) != len(val2):
        return False
    result = 0
    for x, y in zip(val1.encode(), val2.encode()):
        result |= x ^ y
    return result == 0


def verify_facebook_signature(app_secret: str, raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Validate Facebook X-Hub-Signature header (sha1=...) or X-Hub-Signature-256 (sha256=...)."""
    if not signature_header:
        return False

    try:
        if signature_header.startswith("sha1="):
            algo = hashlib.sha1
            provided = signature_header.split("=", 1)[1]
        elif signature_header.startswith("sha256="):
            algo = hashlib.sha256
            provided = signature_header.split("=", 1)[1]
        else:
            parts = signature_header.split("=", 1)
            algo = getattr(hashlib, parts[0])  # type: ignore[attr-defined]
            provided = parts[1]
        mac = hmac.new(app_secret.encode("utf-8"), msg=raw_body, digestmod=algo)
        expected = mac.hexdigest()
        return _const_time_compare(provided, expected)
    except Exception:
        logger.exception("Failed verifying facebook signature")
        return False


def forward_http_json(endpoint: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: float = 5.0, retries: int = 2) -> requests.Response:
    """Forward payload as JSON via HTTP POST with basic retries."""
    if not endpoint:
        raise ValueError("FORWARDING_ENDPOINT is required when SQS URL is not provided")

    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(endpoint, json=payload, headers=headers or {}, timeout=timeout)
            if 200 <= resp.status_code < 300:
                return resp
            # Retry on 5xx
            if 500 <= resp.status_code < 600:
                last_exc = RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
                continue
            # Non-retryable
            resp.raise_for_status()
            return resp
        except Exception as e:  # network error or raise_for_status
            last_exc = e
    assert last_exc is not None
    raise last_exc


def send_to_sqs(sqs_url: str, message: Dict[str, Any], delay_seconds: int = 0) -> Dict[str, Any]:
    """Send a JSON message to SQS. Imports boto3 lazily to avoid local dependency."""
    if not sqs_url:
        raise ValueError("SQS URL is required")
    try:
        import boto3  # type: ignore
        import botocore  # type: ignore
    except Exception as e:
        # In non-Lambda environments, boto3 might not be available
        raise RuntimeError("boto3 is required to send to SQS in this environment") from e

    sqs = boto3.client("sqs")
    try:
        response = sqs.send_message(
            QueueUrl=sqs_url,
            MessageBody=json.dumps(message),
            DelaySeconds=delay_seconds,
        )
        return response
    except Exception:
        logger.exception("Failed pushing message to SQS")
        raise


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if v is not None else default