import json
import hmac
import hashlib
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.bot.channels.facebook.routes import router as fb_router


def make_sig(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha1)
    return f"sha1={mac.hexdigest()}"


def test_verify_webhook_success(monkeypatch):
    app = FastAPI()
    app.include_router(fb_router)

    async def fake_get_facebook_config():
        return {"verify": "token"}

    monkeypatch.setattr("app.bot.channels.facebook.routes.get_facebook_config", fake_get_facebook_config)

    client = TestClient(app)
    r = client.get("/facebook/webhook?hub.mode=subscribe&hub.verify_token=token&hub.challenge=123")
    assert r.status_code == 200
    # Facebook sends the challenge as text, FastAPI returns parsed json, so we convert to int
    assert int(r.text) == 123


def test_verify_webhook_invalid_token(monkeypatch):
    app = FastAPI()
    app.include_router(fb_router)

    async def fake_get_facebook_config():
        return {"verify": "token"}

    monkeypatch.setattr("app.bot.channels.facebook.routes.get_facebook_config", fake_get_facebook_config)

    client = TestClient(app)
    r = client.get("/facebook/webhook?hub.mode=subscribe&hub.verify_token=bad&hub.challenge=123")
    assert r.status_code == 403


def test_post_webhook_invalid_signature(monkeypatch):
    app = FastAPI()
    app.include_router(fb_router)

    async def fake_get_facebook_config():
        return {"verify": "token", "app_secret": "s"}

    class FakeDialogueManager:
        pass

    monkeypatch.setattr("app.bot.channels.facebook.routes.get_facebook_config", fake_get_facebook_config)
    monkeypatch.setattr("app.bot.channels.facebook.routes.get_dialogue_manager", lambda: FakeDialogueManager())

    client = TestClient(app)
    body = {"a": 1}
    r = client.post("/facebook/webhook", json=body, headers={"X-Hub-Signature": "sha1=bad"})
    assert r.status_code == 403


def test_post_webhook_success_queueing(monkeypatch):
    app = FastAPI()
    app.include_router(fb_router)

    async def fake_get_facebook_config():
        return {"verify": "token", "app_secret": "s"}

    class FakeDialogueManager:
        async def process(self):
            pass

    class FakeFacebookReceiver:
        def __init__(self, config, dm):
            pass

        def validate_hub_signature(self, body, sig):
            return True

        async def process_webhook_event(self, data):
            return True

    monkeypatch.setattr("app.bot.channels.facebook.routes.get_facebook_config", fake_get_facebook_config)
    monkeypatch.setattr("app.bot.channels.facebook.routes.get_dialogue_manager", lambda: FakeDialogueManager())
    monkeypatch.setattr("app.bot.channels.facebook.routes.FacebookReceiver", FakeFacebookReceiver)

    client = TestClient(app)
    r = client.post("/facebook/webhook", json={"a": 1}, headers={"X-Hub-Signature": "sha1=ok"})
    assert r.status_code == 200
    assert r.json() == {"success": True}