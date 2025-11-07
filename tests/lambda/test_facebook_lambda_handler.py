import json
import os

from lambda_handlers.webhooks import facebook as fb


def _sig(secret, body: bytes, algo="sha256"):
    import hmac, hashlib
    mac = hmac.new(secret.encode(), msg=body, digestmod=getattr(hashlib, algo))
    return f"{algo}={mac.hexdigest()}"


def test_facebook_get_verify_success(monkeypatch):
    monkeypatch.setenv("FACEBOOK_VERIFY_TOKEN", "tok")
    event = {
        "httpMethod": "GET",
        "queryStringParameters": {"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "321"},
    }
    resp = fb.handler(event, None)
    assert resp["statusCode"] == 200
    assert resp["body"] == "321"


def test_facebook_get_verify_invalid(monkeypatch):
    monkeypatch.setenv("FACEBOOK_VERIFY_TOKEN", "tok")
    event = {"httpMethod": "GET", "queryStringParameters": {"hub.mode": "subscribe", "hub.verify_token": "nope"}}
    resp = fb.handler(event, None)
    assert resp["statusCode"] == 403 or resp["statusCode"] == 400


def test_facebook_post_valid_signature_forwards_http(monkeypatch):
    body = {
        "entry": [
            {
                "id": "page1",
                "messaging": [
                    {"sender": {"id": "u1"}, "timestamp": 1, "message": {"text": "hello"}}
                ],
            }
        ]
    }
    raw = json.dumps(body).encode()
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://internal/ingest")
    monkeypatch.delenv("FORWARDING_SQS_URL", raising=False)

    forwarded = {"calls": []}

    def fake_forward(endpoint, payload, headers=None, timeout=5.0, retries=2):
        forwarded["calls"].append((endpoint, payload, headers or {}))
        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(fb, "forward_http_json", fake_forward)

    event = {
        "httpMethod": "POST",
        "headers": {"X-Hub-Signature-256": _sig("secret", raw)},
        "body": raw.decode(),
        "isBase64Encoded": False,
    }

    resp = fb.handler(event, None)
    assert resp["statusCode"] == 200
    assert forwarded["calls"], "should have forwarded"
    endpoint, msg, headers = forwarded["calls"][0]
    assert endpoint == "https://internal/ingest"
    assert msg["thread_id"] == "u1"
    assert headers["x-source"] == "facebook-webhook"


def test_facebook_post_invalid_signature(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    event = {"httpMethod": "POST", "headers": {"X-Hub-Signature": "sha1=deadbeef"}, "body": "{}"}
    resp = fb.handler(event, None)
    assert resp["statusCode"] == 403


def test_facebook_post_invalid_json(monkeypatch):
    raw = b"not-json"
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    event = {
        "httpMethod": "POST",
        "headers": {"X-Hub-Signature-256": _sig("secret", raw)},
        "body": raw.decode("latin1"),
    }
    resp = fb.handler(event, None)
    assert resp["statusCode"] == 400