import asyncio
from datetime import datetime, timedelta
import pytest
import httpx
from fastapi import HTTPException

from app.admin.chatlogs import routes


@pytest.fixture(autouse=True)
def reset_rate_limiter(monkeypatch):
    """Ensure rate_limiter is reset/mocked for tests to avoid global state issues."""
    class DummyLimiter:
        def __init__(self):
            self.allowed = True
        def allow_request(self, client_id: str) -> bool:
            return self.allowed
    dummy = DummyLimiter()
    monkeypatch.setattr(routes, "rate_limiter", dummy)
    return dummy


def test_validate_date_range_start_after_end_raises():
    """start_date after end_date should raise HTTPException 400"""
    start = datetime.utcnow()
    end = start - timedelta(days=1)
    with pytest.raises(HTTPException) as exc:
        routes.validate_date_range(start_date=start, end_date=end)
    assert exc.value.status_code == 400
    assert "start_date must be before end_date" in str(exc.value.detail)


def test_validate_date_range_too_old_raises():
    """start_date older than 90 days should raise HTTPException 400"""
    old_date = datetime.utcnow() - timedelta(days=91)
    with pytest.raises(HTTPException) as exc:
        routes.validate_date_range(start_date=old_date, end_date=None)
    assert exc.value.status_code == 400
    assert "retention policy" in str(exc.value.detail)


def test_validate_date_range_none_ok():
    """Both dates None should be allowed and return tuple of Nones."""
    result = routes.validate_date_range(start_date=None, end_date=None)
    assert result == (None, None)


@pytest.mark.asyncio
async def test_verify_admin_access_missing_header_raises():
    """Missing Authorization header should raise 401"""
    with pytest.raises(HTTPException) as exc:
        await routes.verify_admin_access(authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_admin_access_invalid_token(monkeypatch):
    """If verify_admin_token raises, verify_admin_access should raise 401"""
    def fake_verify(token: str):
        raise Exception("invalid")
    monkeypatch.setattr(routes, "verify_admin_token", fake_verify)

    with pytest.raises(HTTPException) as exc:
        await routes.verify_admin_access(authorization="Bearer badtoken")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_admin_access_insufficient_role(monkeypatch):
    """Non-admin role should result in 403 Forbidden"""
    def fake_verify(token: str):
        return {"sub": "u1", "role": "user", "email": "x@e.com"}

    monkeypatch.setattr(routes, "verify_admin_token", fake_verify)

    with pytest.raises(HTTPException) as exc:
        await routes.verify_admin_access(authorization="Bearer sometoken")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_admin_access_success(monkeypatch):
    """Valid admin token should return payload dict"""
    payload = {"sub": "admin1", "role": "admin", "email": "admin@x.com"}

    def fake_verify(token: str):
        return payload

    monkeypatch.setattr(routes, "verify_admin_token", fake_verify)

    result = await routes.verify_admin_access(authorization="Bearer goodtoken")
    assert result == payload


def test_mask_pii_various_patterns():
    """Emails, phones, SSNs and cards should be masked in text"""
    text = (
        "Contact me at john.doe@example.com or 555-123-4567. "
        "My SSN is 123-45-6789 and card 4111-1111-1111-1111"
    )
    masked = routes.mask_pii(text)
    assert "[EMAIL_MASKED]" in masked
    assert "[PHONE_MASKED]" in masked
    assert "[SSN_MASKED]" in masked
    assert "[CARD_MASKED]" in masked


def test_apply_pii_filtering_masks_fields():
    """apply_pii_filtering should mask 'user_message.text' and 'bot_message' texts"""
    data = {
        "user_message": {"text": "Reach me at alice@example.com"},
        "bot_message": [
            {"text": "Call 5551234567"},
            {"text": "Card 4111111111111111"}
        ]
    }

    filtered = routes.apply_pii_filtering(data, mask=True)
    # Original structure preserved
    assert "user_message" in filtered
    assert "bot_message" in filtered

    assert "[EMAIL_MASKED]" in filtered["user_message"]["text"]
    # bot messages masked
    assert any("[PHONE_MASKED]" in m["text"] or "[CARD_MASKED]" in m["text"] for m in filtered["bot_message"])


class _DummyResponse:
    def __init__(self, data=None, raise_exc=None):
        self._data = data or {}
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc:
            raise self._raise_exc

    def json(self):
        return self._data


class DummyAsyncClient:
    def __init__(self, response: _DummyResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method, url, params=None, json=None):
        return self._response


@pytest.mark.asyncio
async def test_call_store_api_success(monkeypatch):
    """call_store_api should return parsed JSON on success"""
    expected = {"ok": True, "data": [1, 2, 3]}
    dummy_resp = _DummyResponse(data=expected, raise_exc=None)

    def fake_client(*args, **kwargs):
        return DummyAsyncClient(dummy_resp)

    monkeypatch.setattr(routes.httpx, "AsyncClient", fake_client)

    result = await routes.call_store_api("/list", method="GET", params={})
    assert result == expected


@pytest.mark.asyncio
async def test_call_store_api_http_error(monkeypatch):
    """If the underlying HTTP client raises HTTPError, an HTTPException(503) should be raised"""
    err = httpx.HTTPError("service down")
    dummy_resp = _DummyResponse(data=None, raise_exc=err)

    def fake_client(*args, **kwargs):
        return DummyAsyncClient(dummy_resp)

    monkeypatch.setattr(routes.httpx, "AsyncClient", fake_client)

    with pytest.raises(HTTPException) as exc:
        await routes.call_store_api("/list", method="GET")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_list_chatlogs_rate_limit_exceeded(monkeypatch, reset_rate_limiter):
    """When rate_limiter denies the request, list_chatlogs should raise 429"""
    # make limiter deny
    reset_rate_limiter.allowed = False

    admin_payload = {"sub": "admin1", "role": "admin", "email": "a@b"}

    with pytest.raises(HTTPException) as exc:
        await routes.list_chatlogs(
            page=1,
            limit=10,
            start_date=None,
            end_date=None,
            mask_pii=True,
            user_id=None,
            admin_payload=admin_payload,
            date_range=(None, None),
        )
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_list_chatlogs_success_masks_conversations(monkeypatch, reset_rate_limiter):
    """list_chatlogs should call store API and apply PII masking to conversations"""
    # Ensure allowed
    reset_rate_limiter.allowed = True

    admin_payload = {"sub": "admin1", "role": "admin", "email": "auditor@x"}

    fake_response = {
        "conversations": [
            {
                "user_message": {"text": "user email bob@example.com"},
                "bot_message": [{"text": "call 555-123-4567"}]
            }
        ],
        "meta": {"total": 1}
    }

    async def fake_call(endpoint, method="GET", params=None, json_data=None):
        return fake_response

    monkeypatch.setattr(routes, "call_store_api", fake_call)

    res = await routes.list_chatlogs(
        page=1,
        limit=10,
        start_date=None,
        end_date=None,
        mask_pii=True,
        user_id=None,
        admin_payload=admin_payload,
        date_range=(None, None),
    )

    assert "conversations" in res
    convo = res["conversations"][0]
    assert "[EMAIL_MASKED]" in convo["user_message"]["text"]
    assert any("[PHONE_MASKED]" in m["text"] for m in convo["bot_message"])


@pytest.mark.asyncio
async def test_get_chat_thread_not_found(monkeypatch):
    """If store API returns empty response, endpoint should raise 404"""
    admin_payload = {"sub": "admin1", "role": "admin", "email": "auditor@x"}

    async def fake_call(endpoint, params=None):
        return None

    monkeypatch.setattr(routes, "call_store_api", fake_call)

    with pytest.raises(HTTPException) as exc:
        await routes.get_chat_thread(thread_id="t1", mask_pii=True, admin_payload=admin_payload)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_chat_thread_success_applies_mask(monkeypatch):
    """get_chat_thread should return masked list of messages when found"""
    admin_payload = {"sub": "admin1", "role": "admin", "email": "auditor@x"}

    sample = [
        {"user_message": {"text": "reach me bob@example.com"}},
        {"bot_message": [{"text": "call 555-123-4567"}]} 
    ]

    async def fake_call(endpoint, params=None):
        return sample

    monkeypatch.setattr(routes, "call_store_api", fake_call)

    res = await routes.get_chat_thread(thread_id="t2", mask_pii=True, admin_payload=admin_payload)
    assert isinstance(res, list)
    # both entries should be processed to have masked fields where applicable
    assert any("[EMAIL_MASKED]" in (entry.get("user_message", {}).get("text", "") ) for entry in res)


@pytest.mark.asyncio
async def test_export_to_s3_calls_store_and_returns_metadata(monkeypatch):
    """export_to_s3 should call store export and return expected metadata"""
    admin_payload = {"sub": "admin1", "role": "admin", "email": "auditor@x"}

    async def fake_call(endpoint, method="POST", params=None, json_data=None):
        return {"export_id": "exp123", "s3_url": "https://s3.mock/obj"}

    monkeypatch.setattr(routes, "call_store_api", fake_call)

    res = await routes.export_to_s3(
        start_date=None,
        end_date=None,
        format="json",
        admin_payload=admin_payload,
        date_range=(None, None),
    )

    assert res["export_id"] == "exp123"
    assert res["s3_url"] == "https://s3.mock/obj"
    assert res["status"] == "processing"