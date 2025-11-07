import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bot.channels.rest.routes import router as rest_router


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(rest_router)
    return app


def test_rest_webbook_canonicalizes_and_forwards_http(app, monkeypatch):
    client = TestClient(app)

    payload = {"sender_id": "u1", "message": "hi", "foo": 5}

    forwarded = {"calls": []}

    def fake_forward(endpoint, payload, headers=None, timeout=5.0, retries=2):
        forwarded["calls"].append((endpoint, payload, headers or {}))
        class R:
            status_code = 200
        return R()

    monkeypatch.delenv("FORWARDING_SQS_URL", raising=False)
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://internal/ingest")
    monkeypatch.setattr("app.bot.channels.rest.routes.forward_http_json", fake_forward)

    resp = client.post("/rest/webbook", data=json.dumps(payload))
    assert resp.status_code == 200
    assert resp.json() == {"success": True}

    assert forwarded["calls"], "should have forwarded"
    endpoint, msg, headers = forwarded["calls"][0]
    assert endpoint == "https://internal/ingest"
    assert msg["thread_id"] == "u1"
    assert msg["text"] == "hi"
    assert msg["context"]["foo"] == 5
    assert headers["x-source"] == "rest-webhook"


def test_rest_webbook_forwards_to_sqs_when_configured(app, monkeypatch):
    client = TestClient(app)

    sent = {"calls": []}

    def fake_send(url, message, delay_seconds=0):
        sent["calls"].append((url, message, delay_seconds))
        return {"MessageId": "1"}

    monkeypatch.setenv("FORWARDING_SQS_URL", "https://sqs/q")
    monkeypatch.delenv("FORWARDING_ENDPOINT", raising=False)
    monkeypatch.setattr("app.bot.channels.rest.routes.send_to_sqs", fake_send)

    resp = client.post("/rest/webbook", json={"thread_id": "u2", "text": "yo", "context": {}})
    assert resp.status_code == 200
    assert sent["calls"], "should have sent to SQS"
    url, msg, _ = sent["calls"][0]
    assert url == "https://sqs/q"
    assert msg["thread_id"] == "u2"


def test_rest_webbook_invalid_json(app):
    client = TestClient(app)
    resp = client.post("/rest/webbook", data="not-json")
    assert resp.status_code == 400