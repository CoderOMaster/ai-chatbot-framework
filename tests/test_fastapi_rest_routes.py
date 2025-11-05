import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from app.bot.channels.rest.routes import router as rest_router


def test_webhook_success(monkeypatch):
    app = FastAPI()
    app.include_router(rest_router)

    class FakeDialogueManager:
        async def process(self, user_message):
            class State:
                bot_message = {"text": "hi"}

            return State()

    monkeypatch.setattr("app.bot.channels.rest.routes.get_dialogue_manager", lambda: FakeDialogueManager())

    client = TestClient(app)
    body = {"thread_id": "t", "text": "hello", "context": {}}
    r = client.post("/rest/webhook", json=body)
    assert r.status_code == 200
    assert r.json() == {"text": "hi"}


def test_webhook_dialogue_manager_exception(monkeypatch):
    app = FastAPI()
    app.include_router(rest_router)

    class FakeDialogueManager:
        async def process(self, user_message):
            raise Exception("bad")

    monkeypatch.setattr("app.bot.channels.rest.routes.get_dialogue_manager", lambda: FakeDialogueManager())

    client = TestClient(app)
    body = {"thread_id": "t", "text": "hello", "context": {}}
    r = client.post("/rest/webhook", json=body)
    assert r.status_code in (400, 500)