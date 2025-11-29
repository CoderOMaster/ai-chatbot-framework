import importlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _reload_dependencies_module() -> Any:
    """Helper to import or reload the dependencies module."""
    return importlib.reload(importlib.import_module("app.dependencies"))


@pytest.fixture
def dependencies(monkeypatch: Any) -> Any:
    """Return the dependencies module with remote dialogue manager disabled."""
    for key in (
        "DIALOGUE_MANAGER_SERVICE_URL",
        "DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT",
        "DIALOGUE_MANAGER_SERVICE_RELOAD_ENDPOINT",
        "DIALOGUE_MANAGER_SERVICE_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    module = _reload_dependencies_module()
    module._dialogue_manager = None
    return module


@pytest.fixture
def remote_dependencies(monkeypatch: Any) -> Any:
    """Return the dependencies module configured to proxy requests to a remote service."""
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_URL", "https://remote.example.com/")
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT", "/process-dialogue")
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_RELOAD_ENDPOINT", "/reload-models")
    monkeypatch.setenv("DIALOGUE_MANAGER_SERVICE_TIMEOUT", "5")
    module = _reload_dependencies_module()
    module._dialogue_manager = None
    return module


class _FakeDialogueManager:
    """Simple stand-in for the real dialogue manager used in asynchronous helpers."""

    def __init__(self) -> None:
        self.update_model = MagicMock()

    @classmethod
    async def from_config(cls) -> "_FakeDialogueManager":
        return cls()


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 30.0),
        ("", 30.0),
        ("12.5", 12.5),
        ("0", 0.0),
    ],
)
def test_parse_timeout_returns_expected_value(value: Any, expected: float, dependencies: Any) -> None:
    """_parse_timeout should return the default or parsed float based on the provided input."""

    assert dependencies._parse_timeout(value) == expected


def test_parse_timeout_falls_back_for_invalid_values(dependencies: Any) -> None:
    """An invalid timeout string should log a warning and return the default."""

    assert dependencies._parse_timeout("invalid") == dependencies.DEFAULT_DIALOGUE_MANAGER_TIMEOUT


@pytest.mark.asyncio
async def test_dialogue_manager_client_post_success(monkeypatch: Any, dependencies: Any) -> None:
    """_post should forward the payload and return the parsed dictionary on success."""

    client = dependencies.DialogueManagerClient("https://api.example.com/", "/process", "/reload", timeout=2.5)
    mock_response = SimpleNamespace(body={"thread_id": "abc"})
    mock_call_api = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(dependencies, "call_api", mock_call_api)

    result = await client._post("/process", payload={"foo": "bar"})

    assert result == {"thread_id": "abc"}
    mock_call_api.assert_awaited_once()
    called_url = mock_call_api.call_args[0][0]
    assert called_url == "https://api.example.com/process"
    assert mock_call_api.call_args[1]["parameters"] == {"foo": "bar"}
    assert mock_call_api.call_args[1]["timeout"] == 2.5


@pytest.mark.asyncio
async def test_dialogue_manager_client_post_handles_api_failure(monkeypatch: Any, dependencies: Any) -> None:
    """_post should raise a DialogueManagerClientException when the remote API call fails."""

    client = dependencies.DialogueManagerClient("https://api.example.com", "/process", "/reload", timeout=10)
    mock_failure = AsyncMock(side_effect=dependencies.APICallException("boom"))
    monkeypatch.setattr(dependencies, "call_api", mock_failure)

    with pytest.raises(dependencies.DialogueManagerClientException):
        await client._post("/process")


@pytest.mark.asyncio
async def test_dialogue_manager_client_post_rejects_unexpected_payload(monkeypatch: Any, dependencies: Any) -> None:
    """_post should raise when the response payload is not a dictionary."""

    client = dependencies.DialogueManagerClient("https://api.example.com", "/process", "/reload", timeout=10)
    mock_response = SimpleNamespace(body=["not", "a", "dict"])
    monkeypatch.setattr(dependencies, "call_api", AsyncMock(return_value=mock_response))

    with pytest.raises(dependencies.DialogueManagerClientException):
        await client._post("/process")


@pytest.mark.asyncio
async def test_dialogue_manager_client_process_serializes_message(monkeypatch: Any, dependencies: Any) -> None:
    """process should send the serialized UserMessage payload and decode the state returned by the service."""

    client = dependencies.DialogueManagerClient("https://api.example.com", "/process", "/reload", timeout=5)
    mock_state = {"thread_id": "abc"}
    monkeypatch.setattr(client, "_post", AsyncMock(return_value=mock_state))

    message = dependencies.UserMessage("thread", "hi", {"hello": "world"})
    state = await client.process(message)

    assert isinstance(state, dependencies.State)
    assert state.thread_id == "abc"
    client._post.assert_awaited_once_with("/process", payload=message.to_dict())


@pytest.mark.asyncio
async def test_dialogue_manager_client_reload_delegates_to_post(monkeypatch: Any, dependencies: Any) -> None:
    """reload should make a POST request to the configured reload endpoint."""

    client = dependencies.DialogueManagerClient("https://api.example.com", "/process", "/reload", timeout=3)
    monkeypatch.setattr(client, "_post", AsyncMock())

    await client.reload()

    client._post.assert_awaited_once_with("/reload")


def test_build_remote_client_requires_configuration(dependencies: Any) -> None:
    """_build_remote_client should raise when the remote service is not configured."""

    with pytest.raises(RuntimeError):
        dependencies._build_remote_client()


def test_build_remote_client_returns_configured_client(remote_dependencies: Any) -> None:
    """When remote wiring is enabled, the factory returns a properly configured HTTP client."""

    client = remote_dependencies._build_remote_client()

    assert isinstance(client, remote_dependencies.DialogueManagerClient)
    assert client._base_url == "https://remote.example.com"
    assert client._process_endpoint == "/process-dialogue"
    assert client._reload_endpoint == "/reload-models"
    assert client._timeout == float(remote_dependencies._DIALOGUE_MANAGER_SERVICE_TIMEOUT)


@pytest.mark.asyncio
async def test_get_dialogue_manager_requires_initialization(dependencies: Any) -> None:
    """Calling get_dialogue_manager before init should raise when running as a monolith."""

    dependencies._dialogue_manager = None
    with pytest.raises(RuntimeError):
        await dependencies.get_dialogue_manager()


@pytest.mark.asyncio
async def test_get_dialogue_manager_returns_local_instance(dependencies: Any) -> None:
    """get_dialogue_manager should return the local instance once initialized."""

    sentinel = object()
    dependencies._dialogue_manager = sentinel
    assert await dependencies.get_dialogue_manager() is sentinel


@pytest.mark.asyncio
async def test_get_dialogue_manager_returns_remote_client(remote_dependencies: Any) -> None:
    """When remote wiring is enabled, get_dialogue_manager should proxy requests to the remote client."""

    manager = await remote_dependencies.get_dialogue_manager()

    assert isinstance(manager, remote_dependencies.DialogueManagerClient)


@pytest.mark.asyncio
async def test_set_dialogue_manager_blocks_when_remote_enabled(remote_dependencies: Any) -> None:
    """Remote deployments should not allow replacing the dialogue manager reference."""

    with pytest.raises(RuntimeError):
        await remote_dependencies.set_dialogue_manager(object())


@pytest.mark.asyncio
async def test_set_dialogue_manager_updates_shared_reference(dependencies: Any) -> None:
    """set_dialogue_manager should update the internal singleton when the remote service is disabled."""

    sentinel = object()
    await dependencies.set_dialogue_manager(sentinel)
    assert dependencies._dialogue_manager is sentinel


@pytest.mark.asyncio
async def test_init_dialogue_manager_is_noop_when_remote(remote_dependencies: Any, monkeypatch: Any) -> None:
    """init_dialogue_manager should skip initialization when configured to use the remote service."""

    fake_from_config = AsyncMock()
    monkeypatch.setattr(
        "app.bot.dialogue_manager.dialogue_manager.DialogueManager.from_config",
        fake_from_config,
    )

    await remote_dependencies.init_dialogue_manager()

    fake_from_config.assert_not_awaited()
    assert remote_dependencies._dialogue_manager is None


@pytest.mark.asyncio
async def test_init_dialogue_manager_initializes_local_dialogue_manager(
    dependencies: Any, monkeypatch: Any
) -> None:
    """init_dialogue_manager should load models and store the created manager when running locally."""

    fake_models_dir = "fake-models"
    monkeypatch.setattr(
        "app.bot.dialogue_manager.dialogue_manager.DialogueManager",
        _FakeDialogueManager,
    )
    
    # Create a mock app_config with the fake models directory
    mock_app_config = MagicMock()
    mock_app_config.MODELS_DIR = fake_models_dir
    monkeypatch.setattr(dependencies, "app_config", mock_app_config)
    
    await dependencies.init_dialogue_manager()

    manager = dependencies._dialogue_manager
    assert isinstance(manager, _FakeDialogueManager)
    manager.update_model.assert_called_once_with(fake_models_dir)


@pytest.mark.asyncio
async def test_reload_dialogue_manager_delegates_to_remote_service(remote_dependencies: Any, monkeypatch: Any) -> None:
    """reload_dialogue_manager should request the remote service to reload models when wired remotely."""

    class RemoteClient:
        def __init__(self) -> None:
            self.reload = AsyncMock()

    client = RemoteClient()
    monkeypatch.setattr(remote_dependencies, "_build_remote_client", lambda: client)

    await remote_dependencies.reload_dialogue_manager()

    client.reload.assert_awaited_once()
    assert remote_dependencies._dialogue_manager is None


@pytest.mark.asyncio
async def test_reload_dialogue_manager_refreshes_local_manager(dependencies: Any, monkeypatch: Any) -> None:
    """reload_dialogue_manager should rebuild and store the dialogue manager in monolith deployments."""

    fake_models_dir = "real-models"
    fake_manager = _FakeDialogueManager()
    mock_from_config = AsyncMock(return_value=fake_manager)
    monkeypatch.setattr(
        "app.bot.dialogue_manager.dialogue_manager.DialogueManager.from_config",
        mock_from_config,
    )

    # Create a mock app_config with the fake models directory
    mock_app_config = MagicMock()
    mock_app_config.MODELS_DIR = fake_models_dir
    monkeypatch.setattr(dependencies, "app_config", mock_app_config)
    
    await dependencies.reload_dialogue_manager()

    assert dependencies._dialogue_manager is fake_manager
    fake_manager.update_model.assert_called_once_with(fake_models_dir)
    mock_from_config.assert_awaited_once()


@pytest.mark.asyncio
async def test_reload_dialogue_manager_reuses_setter(dependencies: Any, monkeypatch: Any) -> None:
    """reload_dialogue_manager should call set_dialogue_manager to refresh the global singleton."""

    manager_before = object()
    await dependencies.set_dialogue_manager(manager_before)

    fake_manager = _FakeDialogueManager()
    mock_from_config = AsyncMock(return_value=fake_manager)
    monkeypatch.setattr(
        "app.bot.dialogue_manager.dialogue_manager.DialogueManager.from_config",
        mock_from_config,
    )
    fake_models_dir = "fresh-models"
    
    # Create a mock app_config with the fake models directory
    mock_app_config = MagicMock()
    mock_app_config.MODELS_DIR = fake_models_dir
    monkeypatch.setattr(dependencies, "app_config", mock_app_config)
    
    await dependencies.reload_dialogue_manager()

    assert dependencies._dialogue_manager is fake_manager
    fake_manager.update_model.assert_called_once_with(fake_models_dir)
    mock_from_config.assert_awaited_once()