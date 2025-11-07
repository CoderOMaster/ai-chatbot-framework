import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bot.channels.facebook.routes import router as fb_router


class DummyIntegration:
    def __init__(self, status=True, settings=None):
        self.status = status
        self.settings = settings or {"verify": "token", "secret": "appsecret"}


@pytest.fixture(autouse=True)
def patch_integration(monkeypatch):
    async def fake_get_integration(name):
        return DummyIntegration()

    monkeypatch.setattr("app.bot.channels.facebook.routes.get_integration", fake_get_integration)


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(fb_router)
    return app


def test_verify_webhook_success(app, monkeypatch):
    client = TestClient(app)
    # env override
    monkeypatch.setenv("FACEBOOK_VERIFY_TOKEN", "token")

    resp = client.get("/facebook/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "token", "hub.challenge": "123"})
    assert resp.status_code == 200
    assert resp.json() == 123


def test_verify_webhook_invalid_token(app, monkeypatch):
    client = TestClient(app)
    resp = client.get("/facebook/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "123"})
    assert resp.status_code == 403


def _sig(secret, body: bytes, algo="sha256"):
    import hmac, hashlib
    mac = hmac.new(secret.encode(), msg=body, digestmod=getattr(hashlib, algo))
    return f"{algo}={mac.hexdigest()}"


def test_post_webhook_valid_signature_forwards_background(app, monkeypatch):
    client = TestClient(app)
    body = {
        "entry": [
            {
                "id": "page1",
                "messaging": [
                    {
                        "sender": {"id": "user1"},
                        "timestamp": 111,
                        "message": {"text": "hello"},
                    }
                ],
            }
        ]
    }
    sig = _sig("appsecret", json.dumps(body).encode())

    forwarded = {"calls": []}

    def fake_forward(endpoint, payload, headers=None, timeout=5.0, retries=2):
        forwarded["calls"].append((endpoint, payload, headers or {}))
        class R:
            status_code = 200
        return R()

    monkeypatch.delenv("FORWARDING_SQS_URL", raising=False)
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://internal/ingest")
    monkeypatch.setattr("app.bot.channels.facebook.routes.forward_http_json", fake_forward)

    resp = client.post("/facebook/webhook", data=json.dumps(body), headers={"X-Hub-Signature-256": sig})
    assert resp.status_code == 200
    # Background task executes after response; TestClient runs tasks synchronously
    assert forwarded["calls"], "should have forwarded"
    endpoint, payload, headers = forwarded["calls"][0]
    assert endpoint == "https://internal/ingest"
    assert payload["thread_id"] == "user1"
    assert headers["x-source"] == "facebook-webhook"


def test_post_webhook_rejects_invalid_signature(app):
    client = TestClient(app)
    resp = client.post("/facebook/webhook", data="{}", headers={"X-Hub-Signature": "sha1=deadbeef"})
    assert resp.status_code == 403


def test_post_webhook_invalid_json(app):
    client = TestClient(app)
    resp = client.post("/facebook/webhook", data="not json", headers={"X-Hub-Signature": "sha1=0000000000000000000000000000000000000000"})
    assert resp.status_code == 403 or resp.status_code == 400