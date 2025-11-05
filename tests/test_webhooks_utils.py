import base64
import hmac
import hashlib
import json
import pytest
from app.common import webhooks


def make_sig(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha1)
    return f"sha1={mac.hexdigest()}"


def test_verify_facebook_signature_valid():
    secret = "supersecret"
    body = b'{"hello":"world"}'
    header = make_sig(secret, body)
    assert webhooks.verify_facebook_signature(body, header, secret) is True


def test_verify_facebook_signature_invalid_header_format():
    assert webhooks.verify_facebook_signature(b"x", "invalidformat", "s") is False


def test_verify_facebook_signature_wrong_type():
    secret = "s"
    body = b"x"
    # use sha256 instead of sha1
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    header = f"sha256={mac.hexdigest()}"
    assert webhooks.verify_facebook_signature(body, header, secret) is False


def test_verify_facebook_signature_missing_secret_or_header():
    assert webhooks.verify_facebook_signature(b"x", "", "s") is False
    assert webhooks.verify_facebook_signature(b"x", "sha1=abc", "") is False


def test_parse_lambda_event_body_plain_string():
    event = {"body": "{\"a\":1}", "isBase64Encoded": False, "headers": {"X": "y"}}
    body_bytes, headers = webhooks.parse_lambda_event_body(event)
    assert body_bytes == b'{"a":1}'
    assert headers == {"X": "y"}


def test_parse_lambda_event_body_base64():
    payload = {"a": 1}
    b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    event = {"body": b64, "isBase64Encoded": True, "headers": {"X": "y"}}
    body_bytes, headers = webhooks.parse_lambda_event_body(event)
    assert json.loads(body_bytes.decode("utf-8")) == payload
    assert headers == {"X": "y"}


def test_parse_lambda_event_body_invalid_base64_raises():
    event = {"body": "not-base64!", "isBase64Encoded": True}
    with pytest.raises(ValueError):
        webhooks.parse_lambda_event_body(event)


def test_parse_lambda_event_body_non_dict_event_raises():
    with pytest.raises(ValueError):
        webhooks.parse_lambda_event_body("not-a-dict")


def test_parse_lambda_event_body_none_body_returns_empty_bytes():
    event = {"headers": {}}
    body_bytes, headers = webhooks.parse_lambda_event_body(event)
    assert body_bytes == b""
    assert headers == {}