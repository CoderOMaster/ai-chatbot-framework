import hmac
import hashlib
import json
from typing import Any, Dict, Tuple


def verify_facebook_signature(body_bytes: bytes, header_signature: str, app_secret: str) -> bool:
    """Verify Facebook X-Hub-Signature header against the body using app_secret.

    header_signature is expected in the format 'sha1=<hexdigest>'
    """
    if not header_signature or not app_secret:
        return False
    try:
        sig_type, signature = header_signature.split("=", 1)
    except ValueError:
        return False
    if sig_type != "sha1":
        return False
    mac = hmac.new(app_secret.encode("utf-8"), body_bytes, hashlib.sha1)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_lambda_event_body(event: Dict[str, Any]) -> Tuple[bytes, Dict[str, str]]:
    """Parse AWS Lambda proxy integration event into raw body bytes and headers.

    Supports base64-encoded body when event["isBase64Encoded"] is True.
    Raises ValueError for invalid events.
    """
    if not isinstance(event, dict):
        raise ValueError("Invalid event")
    headers = {}
    # normalise header keys to case-sensitive names used in app (as-is)
    if "headers" in event and isinstance(event["headers"], dict):
        headers = {k: v for k, v in event["headers"].items()}

    body = event.get("body")
    if body is None:
        return b"", headers

    if event.get("isBase64Encoded"):
        import base64

        try:
            return base64.b64decode(body), headers
        except Exception as e:
            raise ValueError("Invalid base64 body") from e

    if isinstance(body, str):
        return body.encode("utf-8"), headers

    # otherwise try to json-dump the body
    try:
        return json.dumps(body).encode("utf-8"), headers
    except Exception:
        raise ValueError("Unable to parse body")