import json
import hashlib
import hmac
import pytest
from fastapi import HTTPException

import app.bot.channels.facebook.routes as routes


class DummyHeaders(dict):
    def get(self, k, default=None):
        return super().get(k, default)


class DummyQueryParams(dict):
    def get(self, k, default=None):
        return super().get(k, default)


class DummyRequest:
    def __init__(self, body_bytes: bytes, headers: dict = None, query_params: dict = None):
        self._body = body_bytes
        self.headers = DummyHeaders(headers or {})
        self.query_params = DummyQueryParams(query_params or {})

    async def body(self) -> bytes:
        return self._body

    async def json(self):
        # Emulate starlette Request.json behavior
        return json.loads(self._body)


@pytest.mark.asyncio
async def test_validate_facebook_config_success(monkeypatch):
    """_validate_facebook_config returns dict when environment is set on module."""
    monkeypatch.setattr(routes, "FACEBOOK_VERIFY_TOKEN", "verify_tok")
    monkeypatch.setattr(routes, "FACEBOOK_SECRET", "secret")
    monkeypatch.setattr(routes, "FACEBOOK_PAGE_ACCESS_TOKEN", "page_token")
    monkeypatch.setattr(routes, "SQS_QUEUE_URL", "https://sqs.example/queue")

    cfg = routes._validate_facebook_config()
    assert cfg["verify"] == "verify_tok"
    assert cfg["secret"] == "secret"
    assert cfg["page_access_token"] == "page_token"


def test_validate_facebook_config_missing(monkeypatch):
    """_validate_facebook_config raises ValueError if settings are missing."""
    monkeypatch.setattr(routes, "FACEBOOK_VERIFY_TOKEN", "")
    monkeypatch.setattr(routes, "FACEBOOK_SECRET", "secret")
    monkeypatch.setattr(routes, "FACEBOOK_PAGE_ACCESS_TOKEN", "page_token")
    monkeypatch.setattr(routes, "SQS_QUEUE_URL", "url")

    with pytest.raises(ValueError):
        routes._validate_facebook_config()


def test_validate_hub_signature_valid():
    """_validate_hub_signature returns True for a valid sha1 HMAC."""
    payload = b'{"hello": "world"}'
    secret = "testsecret"
    digest = hmac.new(bytearray(secret, "utf8"), payload, hashlib.sha1).hexdigest()
    header = f"sha1={digest}"

    assert routes._validate_hub_signature(payload, header, secret) is True


def test_validate_hub_signature_missing_header():
    """_validate_hub_signature returns False if header is missing."""
    payload = b"{}"
    assert routes._validate_hub_signature(payload, "", "secret") is False


def test_generate_webhook_id():
    """_generate_webhook_id creates stable sha256 hash from entry ids and timestamp."""
    data = {"entry": [{"id": "E1"}, {"id": "E2"}], "timestamp": "12345"}
    expected_key = "E1:E2:12345"
    expected_hash = hashlib.sha256(expected_key.encode()).hexdigest()
    assert routes._generate_webhook_id(data) == expected_hash


@pytest.mark.asyncio
async def test_enqueue_webhook_event_success(monkeypatch):
    """_enqueue_webhook_event returns True when sqs send_message succeeds."""
    called = {"ok": False}

    class DummySQS:
        def send_message(self, **kwargs):
            called["ok"] = True
            return {"MessageId": "m1"}

    monkeypatch.setattr(routes, "sqs_client", DummySQS())
    monkeypatch.setattr(routes, "SQS_QUEUE_URL", "https://sqs.queue")

    res = await routes._enqueue_webhook_event({"a": 1})
    assert res is True
    assert called["ok"]


@pytest.mark.asyncio
async def test_enqueue_webhook_event_failure(monkeypatch):
    """_enqueue_webhook_event returns False when SQS client raises."""
    class BadSQS:
        def send_message(self, **_):
            raise Exception("send failed")

    monkeypatch.setattr(routes, "sqs_client", BadSQS())
    monkeypatch.setattr(routes, "SQS_QUEUE_URL", "https://sqs.queue")

    res = await routes._enqueue_webhook_event({"a": 1})
    assert res is False


@pytest.mark.asyncio
async def test_idempotency_store_is_processed_and_mark(monkeypatch):
    """IdempotencyStore uses dynamodb.Table get_item/put_item correctly."""
    # Create a mock table object
    class MockTable:
        def __init__(self):
            self._items = {}

        def get_item(self, Key):
            if Key.get("webhook_id") in self._items:
                return {"Item": self._items[Key.get("webhook_id")]}
            return {}

        def put_item(self, Item):
            self._items[Item["webhook_id"]] = Item

    table = MockTable()

    # Monkeypatch dynamodb.Table factory to return our mock table
    monkeypatch.setattr(routes.dynamodb, "Table", lambda name: table)

    store = routes.IdempotencyStore(table_name="tbl")

    # Initially not processed
    assert await store.is_processed("x") is False

    # Mark processed
    assert await store.mark_processed("x") is True

    # Now is_processed should be True
    assert await store.is_processed("x") is True


@pytest.mark.asyncio
async def test_verify_webhook_success_and_failures(monkeypatch):
    """verify_webhook returns challenge on success and raises HTTPException on failures."""
    monkeypatch.setattr(routes, "FACEBOOK_VERIFY_TOKEN", "mytoken")
    monkeypatch.setattr(routes, "FACEBOOK_SECRET", "secret")
    monkeypatch.setattr(routes, "FACEBOOK_PAGE_ACCESS_TOKEN", "page_tok")
    monkeypatch.setattr(routes, "SQS_QUEUE_URL", "sqs")

    # Success case
    req = DummyRequest(b"", headers={}, query_params={"hub.mode": "subscribe", "hub.verify_token": "mytoken", "hub.challenge": "42"})
    res = await routes.verify_webhook(req)
    assert res == 42

    # Invalid token
    req2 = DummyRequest(b"", headers={}, query_params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"})
    with pytest.raises(HTTPException) as excinfo:
        await routes.verify_webhook(req2)
    assert excinfo.value.status_code == 403

    # Missing params
    req3 = DummyRequest(b"", headers={}, query_params={})
    with pytest.raises(HTTPException) as excinfo2:
        await routes.verify_webhook(req3)
    assert excinfo2.value.status_code == 400


@pytest.mark.asyncio
async def test_webhook_flow_duplicate_and_processing(monkeypatch):
    """webhook endpoint should detect duplicates, mark processed, enqueue, and handle failures gracefully."""
    # Configure module env
    monkeypatch.setattr(routes, "FACEBOOK_VERIFY_TOKEN", "verifytok")
    monkeypatch.setattr(routes, "FACEBOOK_SECRET", "secret")
    monkeypatch.setattr(routes, "FACEBOOK_PAGE_ACCESS_TOKEN", "page_tok")
    monkeypatch.setattr(routes, "SQS_QUEUE_URL", "sqs")

    payload = {"entry": [{"id": "E1", "messaging": [{"mid": "m"}]}], "timestamp": "t"}
    body_bytes = json.dumps(payload).encode()

    # Compute signature header
    digest = hmac.new(bytearray("secret", "utf8"), body_bytes, hashlib.sha1).hexdigest()
    header = f"sha1={digest}"

    # Case 1: duplicate detected -> is_processed True
    class DupStore:
        async def is_processed(self, webhook_id: str):
            return True

        async def mark_processed(self, webhook_id: str):
            return True

    monkeypatch.setattr(routes, "IdempotencyStore", lambda *args, **kwargs: DupStore())

    req_dup = DummyRequest(body_bytes, headers={"X-Hub-Signature": header})
    res_dup = await routes.webhook(req_dup)
    assert res_dup == {"success": True}

    # Case 2: not processed, enqueue succeeds
    called = {"enq": False}

    async def fake_enqueue(data):
        called["enq"] = True
        return True

    class NotDupStore:
        async def is_processed(self, webhook_id: str):
            return False

        async def mark_processed(self, webhook_id: str):
            return True

    monkeypatch.setattr(routes, "IdempotencyStore", lambda *args, **kwargs: NotDupStore())
    monkeypatch.setattr(routes, "_enqueue_webhook_event", fake_enqueue)

    req_ok = DummyRequest(body_bytes, headers={"X-Hub-Signature": header})
    res_ok = await routes.webhook(req_ok)
    assert res_ok == {"success": True}
    assert called["enq"]

    # Case 3: enqueue fails - still returns success
    async def fake_enqueue_fail(data):
        return False

    monkeypatch.setattr(routes, "_enqueue_webhook_event", fake_enqueue_fail)
    req_fail = DummyRequest(body_bytes, headers={"X-Hub-Signature": header})
    res_fail = await routes.webhook(req_fail)
    assert res_fail == {"success": True}


@pytest.mark.asyncio
async def test_webhook_invalid_signature_and_json(monkeypatch):
    """webhook should reject invalid signature and invalid JSON payloads."""
    monkeypatch.setattr(routes, "FACEBOOK_VERIFY_TOKEN", "verifytok")
    monkeypatch.setattr(routes, "FACEBOOK_SECRET", "secret")
    monkeypatch.setattr(routes, "FACEBOOK_PAGE_ACCESS_TOKEN", "page_tok")
    monkeypatch.setattr(routes, "SQS_QUEUE_URL", "sqs")

    # Invalid signature
    payload = {"entry": [], "timestamp": "t"}
    body_bytes = json.dumps(payload).encode()
    bad_header = "sha1=deadbeef"
    req_bad_sig = DummyRequest(body_bytes, headers={"X-Hub-Signature": bad_header})

    with pytest.raises(HTTPException) as exc:
        await routes.webhook(req_bad_sig)
    assert exc.value.status_code == 403

    # Valid signature but invalid JSON (simulate json decode error)
    digest = hmac.new(bytearray("secret", "utf8"), b"notjson", hashlib.sha1).hexdigest()
    header = f"sha1={digest}"

    class BadJSONRequest(DummyRequest):
        async def json(self):
            raise json.JSONDecodeError("msg", "doc", 0)

    req_bad_json = BadJSONRequest(b"notjson", headers={"X-Hub-Signature": header})
    with pytest.raises(HTTPException) as exc2:
        await routes.webhook(req_bad_json)
    assert exc2.value.status_code == 400


@pytest.mark.asyncio
async def test_process_webhook_event_handler_success_and_failure(monkeypatch):
    """process_webhook_event_handler should call FacebookReceiver and handle errors."""
    monkeypatch.setattr(routes, "FACEBOOK_VERIFY_TOKEN", "verifytok")
    monkeypatch.setattr(routes, "FACEBOOK_SECRET", "secret")
    monkeypatch.setattr(routes, "FACEBOOK_PAGE_ACCESS_TOKEN", "page_tok")
    monkeypatch.setattr(routes, "SQS_QUEUE_URL", "sqs")

    payload = {"entry": [{"id": "E1"}], "timestamp": "t"}
    body_bytes = json.dumps(payload).encode()

    # Success path: fake FacebookReceiver.process_webhook_event does not raise
    class FakeReceiverSuccess:
        def __init__(self, config=None, dialogue_manager_url=None):
            pass

        async def process_webhook_event(self, data):
            # simulate processing
            return None

    monkeypatch.setattr(routes, "FacebookReceiver", FakeReceiverSuccess)
    req = DummyRequest(body_bytes)
    res = await routes.process_webhook_event_handler(req)
    assert res == {"success": True}

    # Failure path: process_webhook_event raises
    class FakeReceiverFail:
        def __init__(self, config=None, dialogue_manager_url=None):
            pass

        async def process_webhook_event(self, data):
            raise Exception("boom")

    monkeypatch.setattr(routes, "FacebookReceiver", FakeReceiverFail)
    req2 = DummyRequest(body_bytes)
    with pytest.raises(HTTPException) as excinfo:
        await routes.process_webhook_event_handler(req2)
    assert excinfo.value.status_code == 500

    # Invalid JSON in processing
    class BadJSONReq(DummyRequest):
        async def json(self):
            raise json.JSONDecodeError("msg", "doc", 0)

    bad_req = BadJSONReq(b"notjson")
    with pytest.raises(HTTPException) as excj:
        await routes.process_webhook_event_handler(bad_req)
    assert excj.value.status_code == 400