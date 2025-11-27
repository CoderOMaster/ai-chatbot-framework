import pytest
import asyncio
from typing import Any, Dict, List

from fastapi import HTTPException

import app.admin.integrations.routes as routes
from app.admin.integrations.schemas import Integration, IntegrationUpdate


@pytest.fixture()
def sample_integration() -> Integration:
    """Return a sample Integration object for reuse in tests."""
    return Integration(
        id="int_123",
        name="Test Integration",
        description="A test integration",
        integration_type="slack",
        status="active",
        settings={"webhook_url": "https://hooks.slack.com/services/T000/B000/XXX", "channel": "#alerts"},
    )


@pytest.mark.asyncio
async def test_verify_auth_token_missing_header_raises():
    """verify_auth_token should raise HTTPException 401 when header missing."""
    with pytest.raises(HTTPException) as exc:
        await routes.verify_auth_token(None)
    assert exc.value.status_code == 401
    assert "Missing authorization" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_auth_token_invalid_format_raises():
    """Invalid Authorization header format should raise 401."""
    with pytest.raises(HTTPException) as exc:
        await routes.verify_auth_token("Token abcdefghijklmnop")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_auth_token_short_token_raises():
    """Short bearer token (len < 10) should be rejected."""
    with pytest.raises(HTTPException) as exc:
        await routes.verify_auth_token("Bearer short")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_auth_token_returns_user_id_from_token():
    """A well-formed Bearer token should return the user id (part before first dot)."""
    user = await routes.verify_auth_token("Bearer user123.token.part")
    assert user == "user123"


@pytest.mark.asyncio
async def test_list_integrations_success(monkeypatch, sample_integration: Integration):
    """list_integrations should return the list from store.list_integrations."""

    async def fake_list():
        return [sample_integration]

    monkeypatch.setattr(routes.store, "list_integrations", fake_list)

    result = await routes.list_integrations(user_id="tester")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].id == sample_integration.id


@pytest.mark.asyncio
async def test_list_integrations_runtime_error(monkeypatch):
    """If store.list_integrations raises RuntimeError, an HTTPException(500) should be raised."""

    async def fake_list():
        raise RuntimeError("db down")

    monkeypatch.setattr(routes.store, "list_integrations", fake_list)

    with pytest.raises(HTTPException) as exc:
        await routes.list_integrations(user_id="tester")
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_get_integration_success(monkeypatch, sample_integration: Integration):
    """get_integration should return the Integration when found."""

    async def fake_get(_id: str):
        return sample_integration

    monkeypatch.setattr(routes.store, "get_integration", fake_get)

    result = await routes.get_integration(id=sample_integration.id, user_id="tester")
    assert isinstance(result, Integration)
    assert result.id == sample_integration.id


@pytest.mark.asyncio
async def test_get_integration_not_found(monkeypatch):
    """If store.get_integration returns None, route should raise 404."""

    async def fake_get(_id: str):
        return None

    monkeypatch.setattr(routes.store, "get_integration", fake_get)

    with pytest.raises(HTTPException) as exc:
        await routes.get_integration(id="missing", user_id="tester")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_integration_runtime_error(monkeypatch):
    """RuntimeError in store.get_integration should translate to 500."""

    async def fake_get(_id: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(routes.store, "get_integration", fake_get)

    with pytest.raises(HTTPException) as exc:
        await routes.get_integration(id="any", user_id="tester")
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_test_integration_connection_success(monkeypatch):
    """test_integration_connection should return store.test_connection result."""

    async def fake_test(_id: str):
        return {"ok": True}

    monkeypatch.setattr(routes.store, "test_connection", fake_test)

    result = await routes.test_integration_connection(id="int_123", user_id="tester")
    assert isinstance(result, dict)
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_test_integration_connection_value_error(monkeypatch):
    """When store.test_connection raises ValueError, the route should return 404 with message."""

    async def fake_test(_id: str):
        raise ValueError("not found")

    monkeypatch.setattr(routes.store, "test_connection", fake_test)

    with pytest.raises(HTTPException) as exc:
        await routes.test_integration_connection(id="int_404", user_id="tester")
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail


@pytest.mark.asyncio
async def test_test_integration_connection_exception(monkeypatch):
    """Any other exception in test_connection should return 500."""

    async def fake_test(_id: str):
        raise Exception("network")

    monkeypatch.setattr(routes.store, "test_connection", fake_test)

    with pytest.raises(HTTPException) as exc:
        await routes.test_integration_connection(id="int_err", user_id="tester")
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_update_integration_success(monkeypatch, sample_integration: Integration):
    """update_integration should validate webhook and return updated Integration."""

    async def fake_update(_id: str, payload: IntegrationUpdate, user_id: str):
        # echo back an Integration-like object
        return sample_integration

    monkeypatch.setattr(routes.store, "update_integration", fake_update)

    update_payload = IntegrationUpdate(settings={"webhook_url": "https://example.com/hook"})
    result = await routes.update_integration(id=sample_integration.id, integration=update_payload, user_id="tester")
    assert isinstance(result, Integration)
    assert result.id == sample_integration.id


@pytest.mark.asyncio
async def test_update_integration_invalid_webhook_empty(monkeypatch):
    """Empty webhook_url should produce HTTPException 400."""

    async def fake_update(_id: str, payload: IntegrationUpdate, user_id: str):
        return None

    monkeypatch.setattr(routes.store, "update_integration", fake_update)

    update_payload = IntegrationUpdate(settings={"webhook_url": ""})
    with pytest.raises(HTTPException) as exc:
        await routes.update_integration(id="int_1", integration=update_payload, user_id="tester")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_integration_insecure_http(monkeypatch):
    """A non-localhost http:// webhook should be rejected with 400."""

    async def fake_update(_id: str, payload: IntegrationUpdate, user_id: str):
        return None

    monkeypatch.setattr(routes.store, "update_integration", fake_update)

    update_payload = IntegrationUpdate(settings={"webhook_url": "http://example.com/hook"})
    with pytest.raises(HTTPException) as exc:
        await routes.update_integration(id="int_1", integration=update_payload, user_id="tester")
    assert exc.value.status_code == 400
    assert "HTTPS" in exc.value.detail or "Webhook URL" in exc.value.detail


@pytest.mark.asyncio
async def test_update_integration_webhook_too_long(monkeypatch):
    """Webhook URLs exceeding length limit should be rejected (400)."""

    async def fake_update(_id: str, payload: IntegrationUpdate, user_id: str):
        return None

    monkeypatch.setattr(routes.store, "update_integration", fake_update)

    long_url = "https://" + ("a" * 2050)
    update_payload = IntegrationUpdate(settings={"webhook_url": long_url})
    with pytest.raises(HTTPException) as exc:
        await routes.update_integration(id="int_1", integration=update_payload, user_id="tester")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_integration_not_found(monkeypatch):
    """When store.update_integration returns None, route should raise 404."""

    async def fake_update(_id: str, payload: IntegrationUpdate, user_id: str):
        return None

    monkeypatch.setattr(routes.store, "update_integration", fake_update)

    update_payload = IntegrationUpdate(settings={"webhook_url": "https://safe.example/hook"})
    with pytest.raises(HTTPException) as exc:
        await routes.update_integration(id="missing", integration=update_payload, user_id="tester")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_integration_runtime_error(monkeypatch):
    """RuntimeError raised by store.update_integration should produce HTTPException 500."""

    async def fake_update(_id: str, payload: IntegrationUpdate, user_id: str):
        raise RuntimeError("save failed")

    monkeypatch.setattr(routes.store, "update_integration", fake_update)

    update_payload = IntegrationUpdate(settings={"webhook_url": "https://safe.example/hook"})
    with pytest.raises(HTTPException) as exc:
        await routes.update_integration(id="some", integration=update_payload, user_id="tester")
    assert exc.value.status_code == 500


def test_validate_webhook_url_accepts_https_and_localhost():
    """Directly test the helper _validate_webhook_url for allowed URLs."""
    # Valid https
    routes._validate_webhook_url("https://example.com/hook")
    # Valid localhost http
    routes._validate_webhook_url("http://localhost:8000/hook")


@pytest.mark.parametrize("invalid", [None, 123, "ftp://example.com", "http://example.com/hook", ""])  # noqa: E501
def test_validate_webhook_url_invalid_cases(invalid: Any):
    """Various invalid webhook_url inputs should raise ValueError."""
    with pytest.raises(ValueError):
        routes._validate_webhook_url(invalid)  # type: ignore[arg-type]