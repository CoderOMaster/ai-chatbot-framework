import json
from typing import Any, Dict, Optional

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from app.bot.channels.facebook import routes
from app.bot.dialogue_manager.http_client import APICallException


def _build_request(
    method: str = "GET",
    query_params: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
    body: bytes = b"",
    path: str = "/facebook/webhook",
) -> Request:
    """Helper to construct a Starlette Request with the desired payload."""

    query_string = b""
    if query_params:
        encoded_pairs = [f"{key}={value}".encode() for key, value in query_params.items()]
        query_string = b"&".join(encoded_pairs)

    header_list = []
    if headers:
        header_list = [(name.lower().encode(), value.encode()) for name, value in headers.items()]

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": header_list,
        "client": ("testclient", 5000),
        "server": ("testserver", 80),
        "scheme": "http",
    }

    async def _receive() -> Dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, _receive)


class _DummyResponse:
    def __init__(self, body: Any) -> None:
        self.body = body


@pytest.fixture
def valid_integration_config() -> routes.IntegrationsServiceConfig:
    """Provide a normalized integrations service configuration for testing."""

    return routes.IntegrationsServiceConfig(
        service_url="https://integrations.example.com/",
        timeout_seconds=10.0,
        endpoint_template="/integrations/{integration_name}",
    )


@pytest.mark.asyncio
async def test_integration_repository_builds_normalized_urls(valid_integration_config: routes.IntegrationsServiceConfig) -> None:
    """Ensure the repository trims slashes when constructing the integrations service URL."""

    repository = routes.IntegrationRepository(valid_integration_config)
    assert repository._build_url("facebook") == "https://integrations.example.com/integrations/facebook"


@pytest.mark.asyncio
async def test_fetch_integration_settings_success(monkeypatch: pytest.MonkeyPatch, valid_integration_config: routes.IntegrationsServiceConfig) -> None:
    """Return settings when the integrations service responds with enabled configuration."""

    async def _mock_call_api(url: str, method: str, **kwargs: Any) -> _DummyResponse:
        assert method == "GET"
        assert url.endswith("/integrations/facebook")
        return _DummyResponse({"status": True, "settings": {"verify": "token"}})

    monkeypatch.setattr(routes, "call_api", _mock_call_api)
    repository = routes.IntegrationRepository(valid_integration_config)

    settings = await repository.fetch_integration_settings("facebook")
    assert settings == {"verify": "token"}


@pytest.mark.asyncio
async def test_fetch_integration_settings_uses_integration_nested_settings(monkeypatch: pytest.MonkeyPatch, valid_integration_config: routes.IntegrationsServiceConfig) -> None:
    """Respect the nested `integration.settings` payload when top-level settings are missing."""

    async def _mock_call_api(*_: Any, **__: Any) -> _DummyResponse:  # noqa: ARG002
        return _DummyResponse({"status": True, "integration": {"settings": {"verify": "nested-token"}}})

    monkeypatch.setattr(routes, "call_api", _mock_call_api)
    repository = routes.IntegrationRepository(valid_integration_config)

    settings = await repository.fetch_integration_settings("facebook")
    assert settings == {"verify": "nested-token"}


@pytest.mark.asyncio
async def test_fetch_integration_settings_handles_api_error(monkeypatch: pytest.MonkeyPatch, valid_integration_config: routes.IntegrationsServiceConfig) -> None:
    """Convert APICallException into a 502 HTTPException when integrations service is unreachable."""

    async def _mock_call_api(*_: Any, **__: Any) -> None:
        raise APICallException("boom")

    monkeypatch.setattr(routes, "call_api", _mock_call_api)
    repository = routes.IntegrationRepository(valid_integration_config)

    with pytest.raises(HTTPException) as excinfo:
        await repository.fetch_integration_settings("facebook")
    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_fetch_integration_settings_rejects_non_dict_payload(monkeypatch: pytest.MonkeyPatch, valid_integration_config: routes.IntegrationsServiceConfig) -> None:
    """Raise HTTPException when the integrations service responds with an unexpected payload format."""

    async def _mock_call_api(*_: Any, **__: Any) -> _DummyResponse:  # noqa: ARG002
        return _DummyResponse([1, 2, 3])

    monkeypatch.setattr(routes, "call_api", _mock_call_api)
    repository = routes.IntegrationRepository(valid_integration_config)

    with pytest.raises(HTTPException) as excinfo:
        await repository.fetch_integration_settings("facebook")
    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_fetch_integration_settings_reports_disabled_integration(monkeypatch: pytest.MonkeyPatch, valid_integration_config: routes.IntegrationsServiceConfig) -> None:
    """Return 404 when the integrations service reports an integration is disabled."""

    async def _mock_call_api(*_: Any, **__: Any) -> _DummyResponse:  # noqa: ARG002
        return _DummyResponse({"status": False, "settings": {}})

    monkeypatch.setattr(routes, "call_api", _mock_call_api)
    repository = routes.IntegrationRepository(valid_integration_config)

    with pytest.raises(HTTPException) as excinfo:
        await repository.fetch_integration_settings("facebook")
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_fetch_integration_settings_missing_settings(monkeypatch: pytest.MonkeyPatch, valid_integration_config: routes.IntegrationsServiceConfig) -> None:
    """Raise HTTPException when the integrations payload lacks any settings dictionary."""

    async def _mock_call_api(*_: Any, **__: Any) -> _DummyResponse:  # noqa: ARG002
        return _DummyResponse({"status": True})

    monkeypatch.setattr(routes, "call_api", _mock_call_api)
    repository = routes.IntegrationRepository(valid_integration_config)

    with pytest.raises(HTTPException) as excinfo:
        await repository.fetch_integration_settings("facebook")
    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_fetch_integration_settings_requires_supplier(monkeypatch: pytest.MonkeyPatch, valid_integration_config: routes.IntegrationsServiceConfig) -> None:
    """Ensure that integrations fetch fails when settings are not dictionaries."""

    async def _mock_call_api(*_: Any, **__: Any) -> _DummyResponse:  # noqa: ARG002
        return _DummyResponse({"status": True, "settings": "not-a-dict"})

    monkeypatch.setattr(routes, "call_api", _mock_call_api)
    repository = routes.IntegrationRepository(valid_integration_config)

    with pytest.raises(HTTPException) as excinfo:
        await repository.fetch_integration_settings("facebook")
    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_get_facebook_config_delegates_to_repository() -> None:
    """Ensure the FastAPI dependency forwards the request to the injected repository."""

    class StubRepository:
        def __init__(self) -> None:
            self.called_with: Optional[str] = None

        async def fetch_integration_settings(self, name: str) -> Dict[str, Any]:
            self.called_with = name
            return {"verify": "xxx"}

    repository = StubRepository()
    result = await routes.get_facebook_config(repository=repository)  # type: ignore[arg-type]
    assert result == {"verify": "xxx"}
    assert repository.called_with == "facebook"


@pytest.mark.asyncio
async def test_verify_webhook_success() -> None:
    """Validate the webhook endpoint returns the challenge when tokens match."""

    request = _build_request(
        method="GET",
        query_params={
            "hub.mode": "subscribe",
            "hub.verify_token": "expected",
            "hub.challenge": "123",
        },
    )
    config = {"verify": "expected"}

    response = await routes.verify_webhook(request=request, config=config)
    assert response == 123


@pytest.mark.asyncio
async def test_verify_webhook_invalid_token() -> None:
    """Return HTTP 403 when the verification token does not match."""

    request = _build_request(
        method="GET",
        query_params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "0",
        },
    )
    with pytest.raises(HTTPException) as excinfo:
        await routes.verify_webhook(request=request, config={"verify": "expected"})
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_webhook_missing_parameters() -> None:
    """Return HTTP 400 when required webhook query parameters are missing."""

    request = _build_request(method="GET", query_params={"hub.verify_token": "any"})
    with pytest.raises(HTTPException) as excinfo:
        await routes.verify_webhook(request=request, config={"verify": "expected"})
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_verify_webhook_challenge_not_int() -> None:
    """Guard against non-numeric challenges by relying on ValueError propagation."""

    request = _build_request(
        method="GET",
        query_params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token",
            "hub.challenge": "not-a-number",
        },
    )
    with pytest.raises(ValueError):
        await routes.verify_webhook(request=request, config={"verify": "token"})


def test_parse_timeout_falls_back_to_default() -> None:
    """Blank timeout values should fall back to the provided default."""

    assert routes._parse_timeout(None, 5.5) == 5.5
    assert routes._parse_timeout("", 5.5) == 5.5


def test_parse_timeout_accepts_numeric_strings() -> None:
    """Numeric strings should be converted into floats."""

    assert routes._parse_timeout("7.25", 5.0) == pytest.approx(7.25)


def test_parse_timeout_logs_and_falls_back() -> None:
    """Invalid numeric strings should not raise but fall back to defaults."""

    assert routes._parse_timeout("not-a-number", 3.14) == pytest.approx(3.14)


def test_parse_timeout_custom_value() -> None:
    """Allow overriding the timeout with a valid string representation."""

    assert routes._parse_timeout("2", 4.5) == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_get_remote_dialogue_manager_client_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remote client factory should raise when the dialogue manager service URL is missing."""

    monkeypatch.delenv("DIALOGUE_MANAGER_SERVICE_URL", raising=False)
    with pytest.raises(RuntimeError):
        await routes.get_remote_dialogue_manager_client()


@pytest.mark.asyncio
async def test_get_remote_dialogue_manager_client_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory should honor environment overrides and return a configured client."""

    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_URL", "https://dm.example.com/")
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT", "/process")
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_RELOAD_ENDPOINT", "/reload")
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_TIMEOUT", "12.5")

    client = await routes.get_remote_dialogue_manager_client()
    assert client._timeout == pytest.approx(12.5)
    assert client._build_url("/foo") == "https://dm.example.com/foo"


@pytest.mark.asyncio
async def test_get_remote_dialogue_manager_client_invalid_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid timeout values in the environment should default to module constants."""

    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_URL", "https://dm.example.com")
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_TIMEOUT", "invalid")

    client = await routes.get_remote_dialogue_manager_client()
    assert client._timeout == pytest.approx(routes.DEFAULT_DIALOGUE_MANAGER_TIMEOUT)


@pytest.mark.asyncio
async def test_get_remote_dialogue_manager_client_default_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify defaults are used when specific endpoints are not provided."""

    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_URL", "https://dm.example.com")
    monkeypatch.delenv("DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT", raising=False)
    monkeypatch.delenv("DIALOGUE_MANAGER_SERVICE_RELOAD_ENDPOINT", raising=False)

    client = await routes.get_remote_dialogue_manager_client()
    assert client._build_url("dialogue/process") == "https://dm.example.com/dialogue/process"
    assert client._build_url("dialogue/reload") == "https://dm.example.com/dialogue/reload"


@pytest.mark.asyncio
async def test_webhook_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Webhook should queue the processing task when the signature validates."""

    class FakeFacebookReceiver:
        def __init__(self, config: Dict[str, Any], dialogue_manager_client: Any) -> None:
            self.config = config

        def validate_hub_signature(self, _: bytes, __: str) -> bool:  # noqa: ARG002
            return True

        async def process_webhook_event(self, data: Dict[str, Any]) -> None:  # noqa: ARG002
            pass

    monkeypatch.setattr(routes, "FacebookReceiver", FakeFacebookReceiver)

    background_tasks = BackgroundTasks()
    payload = json.dumps({"hello": "world"}).encode()
    request = _build_request(
        method="POST",
        headers={"X-Hub-Signature": "sig"},
        body=payload,
    )

    response = await routes.webhook(
        background_tasks=background_tasks,
        request=request,
        config={"verify": "unused"},
        dialogue_manager_client=object(),
    )

    assert response == {"success": True}
    assert len(background_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_webhook_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject requests where the Facebook signature validation fails."""

    class FakeFacebookReceiver:
        def __init__(self, config: Dict[str, Any], dialogue_manager_client: Any) -> None:  # noqa: ARG002
            pass

        def validate_hub_signature(self, _: bytes, __: str) -> bool:  # noqa: ARG002
            return False

        async def process_webhook_event(self, data: Dict[str, Any]) -> None:  # noqa: ARG002
            pass

    monkeypatch.setattr(routes, "FacebookReceiver", FakeFacebookReceiver)

    request = _build_request(method="POST", headers={"X-Hub-Signature": "sig"}, body=b"{}")
    with pytest.raises(HTTPException) as excinfo:
        await routes.webhook(
            background_tasks=BackgroundTasks(),
            request=request,
            config={"verify": "unused"},
            dialogue_manager_client=object(),
        )
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_webhook_processing_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Propagate JSON parsing errors as HTTP 500 responses without queuing work."""

    class FakeFacebookReceiver:
        def __init__(self, config: Dict[str, Any], dialogue_manager_client: Any) -> None:  # noqa: ARG002
            pass

        def validate_hub_signature(self, _: bytes, __: str) -> bool:  # noqa: ARG002
            return True

        async def process_webhook_event(self, data: Dict[str, Any]) -> None:  # noqa: ARG002
            pass

    monkeypatch.setattr(routes, "FacebookReceiver", FakeFacebookReceiver)

    request = _build_request(method="POST", headers={"X-Hub-Signature": "sig"}, body=b"not-json")

    async def _fail_json() -> Any:
        raise ValueError("invalid json")

    monkeypatch.setattr(request, "json", _fail_json)

    background_tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as excinfo:
        await routes.webhook(
            background_tasks=background_tasks,
            request=request,
            config={"verify": "unused"},
            dialogue_manager_client=object(),
        )
    assert excinfo.value.status_code == 500
    assert len(background_tasks.tasks) == 0