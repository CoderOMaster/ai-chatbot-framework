import asyncio
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app import main as gateway
from app.main import ServiceRegistry


class MockResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200, headers: Dict[str, str] | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}

    def json(self) -> Dict[str, Any]:
        return self._payload


class MockClient:
    def __init__(self, response: MockResponse, raise_exc: Exception | None = None):
        self._response = response
        self._raise = raise_exc

    async def request(self, method: str, url: str, headers: Dict[str, Any] | None = None, content: bytes | None = None):
        if self._raise:
            raise self._raise
        return self._response


@pytest.fixture
def client() -> TestClient:
    """TestClient fixture for the gateway app."""
    return TestClient(gateway.app)


@pytest.fixture
def simple_registry() -> ServiceRegistry:
    """Provide a fresh ServiceRegistry for tests."""
    return ServiceRegistry(service_urls={"admin": "http://admin", "bot": "http://bot", "dialogue": "http://dialogue"})


def test_service_registry_basic_operations(simple_registry: ServiceRegistry) -> None:
    """ServiceRegistry should return urls for healthy services and reflect health changes."""
    # Initially healthy
    assert simple_registry.get_service_url("admin") == "http://admin"
    assert simple_registry.get_service_url("bot") == "http://bot"
    # Mark admin unhealthy
    simple_registry.mark_unhealthy("admin")
    assert simple_registry.get_service_url("admin") is None
    # Unknown service returns None
    assert simple_registry.get_service_url("unknown") is None
    # Mark admin healthy again
    simple_registry.mark_healthy("admin")
    assert simple_registry.get_service_url("admin") == "http://admin"


def _override_http_client(mock_client: MockClient):
    """Return an async generator function compatible with FastAPI dependency overrides."""

    async def _get_client():
        yield mock_client

    return _get_client


def test_health_and_ready_endpoints(client: TestClient) -> None:
    """/health and /ready endpoints should return basic gateway statuses."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "api-gateway"}

    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "service": "api-gateway"}

    r = client.get("/")
    assert r.status_code == 200
    assert "AI Chatbot Framework API Gateway" in r.json().get("message", "")


def test_services_health_reflects_registry(client: TestClient, simple_registry: ServiceRegistry, monkeypatch) -> None:
    """/services/health should reflect the injected service registry health status."""
    # Replace the module-level registry with our simple one
    monkeypatch.setattr(gateway, "service_registry", simple_registry)

    # Mark bot unhealthy
    simple_registry.mark_unhealthy("bot")

    r = client.get("/services/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["gateway"] == "healthy"
    assert payload["services"]["admin"] is True
    assert payload["services"]["bot"] is False


def test_admin_proxy_success(client: TestClient, simple_registry: ServiceRegistry, monkeypatch) -> None:
    """Admin proxy should forward request and mark service healthy on success."""
    monkeypatch.setattr(gateway, "service_registry", simple_registry)

    resp_payload = {"ok": True, "from": "admin"}
    mock_resp = MockResponse(resp_payload, status_code=200, headers={"x-test": "1"})
    mock_client = MockClient(mock_resp)

    # Override HTTP client dependency
    gateway.app.dependency_overrides[gateway.get_http_client] = _override_http_client(mock_client)

    # Ensure admin is initially healthy
    simple_registry.mark_unhealthy("admin")
    assert simple_registry.get_service_url("admin") is None

    r = client.get("/admin/status")
    # Since the mock registry marks admin as unhealthy initially, the endpoint should return 503
    assert r.status_code == 503

    # Mark admin healthy and try again
    simple_registry.mark_healthy("admin")
    r = client.get("/admin/status")
    assert r.status_code == 200
    assert r.json() == resp_payload
    # The service should remain healthy after successful proxied call
    assert simple_registry.health_status["admin"] is True

    # Cleanup dependency override
    gateway.app.dependency_overrides.pop(gateway.get_http_client, None)


def test_admin_proxy_client_exception_marks_unhealthy(client: TestClient, simple_registry: ServiceRegistry, monkeypatch) -> None:
    """If the downstream admin client raises, the gateway should mark the service unhealthy and return 503."""
    monkeypatch.setattr(gateway, "service_registry", simple_registry)

    # Ensure admin is healthy at start
    simple_registry.mark_healthy("admin")
    assert simple_registry.get_service_url("admin") == "http://admin"

    mock_client = MockClient(MockResponse({}), raise_exc=RuntimeError("down"))
    gateway.app.dependency_overrides[gateway.get_http_client] = _override_http_client(mock_client)

    r = client.post("/admin/do-something", json={"a": 1})
    assert r.status_code == 503
    assert r.json()["detail"] == "Admin service error"
    # Service should be marked unhealthy
    assert simple_registry.health_status["admin"] is False

    gateway.app.dependency_overrides.pop(gateway.get_http_client, None)


@pytest.mark.parametrize("prefix,service_key,detail", [
    ("/bots/test", "bot", "Bot service unavailable"),
    ("/dialogue/test", "dialogue", "Dialogue service unavailable"),
])
def test_service_unavailable_returns_503(client: TestClient, simple_registry: ServiceRegistry, monkeypatch, prefix: str, service_key: str, detail: str) -> None:
    """If a service is marked unhealthy, the gateway should return 503 for that service path."""
    monkeypatch.setattr(gateway, "service_registry", simple_registry)
    # Mark service unhealthy
    simple_registry.mark_unhealthy(service_key)

    r = client.get(prefix)
    assert r.status_code == 503
    assert r.json()["detail"] == detail


def test_bot_and_dialogue_proxies_success(client: TestClient, simple_registry: ServiceRegistry, monkeypatch) -> None:
    """Bot and Dialogue proxies should forward requests correctly and propagate response content and headers."""
    monkeypatch.setattr(gateway, "service_registry", simple_registry)

    bot_payload = {"bot": "ok"}
    dialogue_payload = {"dialogue": "ok"}

    # Test bot proxy success
    bot_resp = MockResponse(bot_payload, status_code=201, headers={"x-bot": "1"})
    bot_client = MockClient(bot_resp)
    gateway.app.dependency_overrides[gateway.get_http_client] = _override_http_client(bot_client)

    r = client.put("/bots/123", json={"update": True})
    assert r.status_code == 201
    assert r.json() == bot_payload
    assert r.headers.get("x-bot") == "1"
    assert simple_registry.health_status["bot"] is True

    gateway.app.dependency_overrides.pop(gateway.get_http_client, None)

    # Test dialogue proxy success
    dialogue_resp = MockResponse(dialogue_payload, status_code=200, headers={"x-dialogue": "1"})
    dialogue_client = MockClient(dialogue_resp)
    gateway.app.dependency_overrides[gateway.get_http_client] = _override_http_client(dialogue_client)

    r = client.patch("/dialogue/flow", json={"step": 2})
    assert r.status_code == 200
    assert r.json() == dialogue_payload
    assert r.headers.get("x-dialogue") == "1"
    assert simple_registry.health_status["dialogue"] is True

    gateway.app.dependency_overrides.pop(gateway.get_http_client, None)