import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

import app.admin.bots.routes as routes


# Helper async upload file mimicking FastAPI's UploadFile
class DummyUploadFile:
    def __init__(self, content_type: str, data: bytes):
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


@pytest.fixture(autouse=True)
def clear_rate_limit_store():
    """Clear the in-memory rate limit store before each test to avoid cross-test pollution."""
    routes._rate_limit_store.clear()
    yield
    routes._rate_limit_store.clear()


@pytest.mark.asyncio
async def test_verify_api_key_missing():
    """Missing API key should raise 401 Unauthorized."""
    with pytest.raises(HTTPException) as exc:
        await routes.verify_api_key(None)
    assert exc.value.status_code == 401
    assert "Missing API key" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_api_key_invalid_short():
    """API keys shorter than expected should be rejected with 401."""
    with pytest.raises(HTTPException) as exc:
        await routes.verify_api_key("short")
    assert exc.value.status_code == 401
    assert "Invalid API key" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_api_key_valid():
    """Valid API key should be returned unchanged."""
    key = "validapikey123"
    returned = await routes.verify_api_key(key)
    assert returned == key


def test_check_rate_limit_allows_under_limit():
    """Requests under the configured rate limit should pass without error."""
    client = "client-1"
    # Should not raise
    for _ in range(5):
        routes.check_rate_limit(client)
    assert len(routes._rate_limit_store[client]) == 5


def test_check_rate_limit_exceeded():
    """When request count equals or exceeds RATE_LIMIT_REQUESTS, a 429 is raised."""
    client = "client-2"
    # Populate timestamps within the window
    now = datetime.utcnow().timestamp()
    routes._rate_limit_store[client] = [now for _ in range(routes.RATE_LIMIT_REQUESTS)]
    with pytest.raises(HTTPException) as exc:
        routes.check_rate_limit(client)
    assert exc.value.status_code == 429
    assert "Rate limit exceeded" in exc.value.detail


def test_check_rate_limit_cleans_old_entries():
    """Old entries outside the rate limit window should be cleaned allowing new requests."""
    client = "client-3"
    old = (datetime.utcnow() - timedelta(seconds=routes.RATE_LIMIT_WINDOW_SECONDS + 10)).timestamp()
    routes._rate_limit_store[client] = [old for _ in range(routes.RATE_LIMIT_REQUESTS)]
    # Now this should be allowed because previous are outside the window
    routes.check_rate_limit(client)
    assert len(routes._rate_limit_store[client]) == 1


@pytest.mark.asyncio
async def test_validate_import_file_invalid_type():
    """Files with invalid content types should be rejected with 400."""
    f = DummyUploadFile("application/octet-stream", b"{}")
    with pytest.raises(HTTPException) as exc:
        await routes.validate_import_file(f)
    assert exc.value.status_code == 400
    assert "Invalid file type" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_import_file_too_large():
    """Files larger than MAX_FILE_SIZE_BYTES should be rejected with 413."""
    large = b"x" * (routes.MAX_FILE_SIZE_BYTES + 1)
    f = DummyUploadFile("application/json", large)
    with pytest.raises(HTTPException) as exc:
        await routes.validate_import_file(f)
    assert exc.value.status_code == 413
    assert "File too large" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_import_file_invalid_json():
    """Invalid JSON should raise a 400 with detail about JSON error."""
    f = DummyUploadFile("application/json", b"not-a-json")
    with pytest.raises(HTTPException) as exc:
        await routes.validate_import_file(f)
    assert exc.value.status_code == 400
    assert "Invalid JSON" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_import_file_missing_keys():
    """JSON that doesn't contain intents or entities should be rejected with 400."""
    data = json.dumps({"some": "value"}).encode()
    f = DummyUploadFile("application/json", data)
    with pytest.raises(HTTPException) as exc:
        await routes.validate_import_file(f)
    assert exc.value.status_code == 400
    assert "Import file must contain 'intents' or 'entities' keys" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_import_file_success():
    """Valid JSON file containing intents or entities should be parsed and returned."""
    payload = {"intents": [{"name": "greet"}], "entities": []}
    data = json.dumps(payload).encode()
    f = DummyUploadFile("application/json", data)
    result = await routes.validate_import_file(f)
    assert isinstance(result, dict)
    assert "intents" in result


# Mocked store exceptions and helpers
class DummyBotNotFoundError(Exception):
    pass


class DummyBotStoreError(Exception):
    pass


@pytest.mark.asyncio
async def test_set_config_success(monkeypatch):
    """Successful config update should call store.update_nlu_config and return a ConfigUpdateResponse."""
    # Prepare a valid request
    req = routes.NLUConfigRequest(config={"a": 1})

    async def fake_update(name, config):
        return None

    # Attach dummy exceptions on the store to be used by the route
    monkeypatch.setattr(routes.store, "BotNotFoundError", DummyBotNotFoundError, raising=False)
    monkeypatch.setattr(routes.store, "BotStoreError", DummyBotStoreError, raising=False)
    monkeypatch.setattr(routes.store, "update_nlu_config", fake_update)

    resp = await routes.set_config("mybot", req, api_key="validapikey123")
    assert resp.message == "Config updated successfully"
    assert hasattr(resp, "updated_at")


@pytest.mark.asyncio
async def test_set_config_too_large(monkeypatch):
    """Oversized configuration JSON should raise 413."""
    # Create a config that exceeds MAX_CONFIG_SIZE_BYTES when serialized
    big_value = "x" * (routes.MAX_CONFIG_SIZE_BYTES + 10)
    req = routes.NLUConfigRequest(config={"big": big_value})

    with pytest.raises(HTTPException) as exc:
        await routes.set_config("mybot", req, api_key="validapikey123")
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_set_config_bot_not_found(monkeypatch):
    """If the store raises BotNotFoundError, endpoint should return 404."""
    async def fake_update(name, config):
        raise DummyBotNotFoundError()

    monkeypatch.setattr(routes.store, "BotNotFoundError", DummyBotNotFoundError, raising=False)
    monkeypatch.setattr(routes.store, "update_nlu_config", fake_update)

    req = routes.NLUConfigRequest(config={"a": 1})
    with pytest.raises(HTTPException) as exc:
        await routes.set_config("nope", req, api_key="validapikey123")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_set_config_store_error(monkeypatch):
    """If the store raises a generic store error, endpoint should return 500."""
    async def fake_update(name, config):
        raise DummyBotStoreError("boom")

    monkeypatch.setattr(routes.store, "BotStoreError", DummyBotStoreError, raising=False)
    monkeypatch.setattr(routes.store, "update_nlu_config", fake_update)

    req = routes.NLUConfigRequest(config={"a": 1})
    with pytest.raises(HTTPException) as exc:
        await routes.set_config("mybot", req, api_key="validapikey123")
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_get_config_success(monkeypatch):
    """Getting a config should return the dictionary returned by the store."""
    async def fake_get(name):
        return {"intent_classifier": "sklearn"}

    monkeypatch.setattr(routes.store, "get_nlu_config", fake_get)

    resp = await routes.get_config("mybot", api_key="validapikey123")
    assert isinstance(resp, dict)
    assert resp["intent_classifier"] == "sklearn"


@pytest.mark.asyncio
async def test_get_config_not_found(monkeypatch):
    """If store reports bot not found, endpoint returns 404."""
    async def fake_get(name):
        raise DummyBotNotFoundError()

    monkeypatch.setattr(routes.store, "BotNotFoundError", DummyBotNotFoundError, raising=False)
    monkeypatch.setattr(routes.store, "get_nlu_config", fake_get)

    with pytest.raises(HTTPException) as exc:
        await routes.get_config("nope", api_key="validapikey123")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_export_bot_success(monkeypatch):
    """Export should return a Response with JSON content and proper headers."""
    payload = {"intents": [], "entities": []}

    async def fake_export(name):
        return payload

    monkeypatch.setattr(routes.store, "export_bot", fake_export)

    resp = await routes.export_bot("mybot", api_key="validapikey123")
    # render() will produce bytes for the Response content
    body_bytes = resp.render()
    assert json.loads(body_bytes.decode()) == payload
    assert resp.media_type == "application/json"
    assert "attachment;filename=bot_mybot_export.json" in resp.headers.get("Content-Disposition", "")


@pytest.mark.asyncio
async def test_export_bot_not_found(monkeypatch):
    """If the store raises BotNotFoundError during export, a 404 should be returned."""
    async def fake_export(name):
        raise DummyBotNotFoundError()

    monkeypatch.setattr(routes.store, "BotNotFoundError", DummyBotNotFoundError, raising=False)
    monkeypatch.setattr(routes.store, "export_bot", fake_export)

    with pytest.raises(HTTPException) as exc:
        await routes.export_bot("nope", api_key="validapikey123")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_import_bot_success(monkeypatch):
    """Importing a valid JSON file should call store.import_bot and return statistics."""
    payload = {"intents": [{"name": "g"}], "entities": []}
    data = json.dumps(payload).encode()
    f = DummyUploadFile("application/json", data)

    async def fake_import(name, data):
        return {"num_intents_created": 1, "num_entities_created": 0}

    monkeypatch.setattr(routes.store, "import_bot", fake_import)

    resp = await routes.import_bot("mybot", file=f, api_key="validapikey123")
    assert resp.num_intents_created == 1
    assert resp.num_entities_created == 0


@pytest.mark.asyncio
async def test_import_bot_invalid_file(monkeypatch):
    """An invalid file should cause the import endpoint to propagate a 400 HTTPException."""
    f = DummyUploadFile("application/octet-stream", b"{}")

    # Ensure store.import_bot is not called or needed
    with pytest.raises(HTTPException) as exc:
        await routes.import_bot("mybot", file=f, api_key="validapikey123")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_import_bot_store_error(monkeypatch):
    """If the store raises a BotStoreError during import, endpoint should return 500."""
    payload = {"intents": [], "entities": []}
    data = json.dumps(payload).encode()
    f = DummyUploadFile("application/json", data)

    async def fake_import(name, data):
        raise DummyBotStoreError("fail")

    monkeypatch.setattr(routes.store, "BotStoreError", DummyBotStoreError, raising=False)
    monkeypatch.setattr(routes.store, "import_bot", fake_import)

    with pytest.raises(HTTPException) as exc:
        await routes.import_bot("mybot", file=f, api_key="validapikey123")
    assert exc.value.status_code == 500


def test_set_config_rate_limiting(monkeypatch):
    """When a client exceeds rate limit, endpoints should raise 429 before calling store."""
    client = "rate-limit-client"
    now = datetime.utcnow().timestamp()
    # Fill store with recent timestamps
    routes._rate_limit_store[client] = [now for _ in range(routes.RATE_LIMIT_REQUESTS)]

    # Prepare minimal valid NLU request
    req = routes.NLUConfigRequest(config={"a": 1})

    # Call set_config synchronously by running the coroutine
    async def call():
        await routes.set_config("mybot", req, api_key=client)

    with pytest.raises(HTTPException) as exc:
        asyncio.get_event_loop().run_until_complete(call())
    assert exc.value.status_code == 429