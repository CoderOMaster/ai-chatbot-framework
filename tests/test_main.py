import pytest
import pytest_asyncio
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncClient, ASGITransport

from app.main import _bot_lifespan, admin_app, bot_app


@pytest_asyncio.fixture
async def admin_client() -> AsyncClient:
    """Create an AsyncClient bound to the admin FastAPI app."""
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://admin") as client:
        yield client


@pytest_asyncio.fixture
async def bot_client() -> AsyncClient:
    """Create an AsyncClient bound to the bot FastAPI app."""
    transport = ASGITransport(app=bot_app)
    async with AsyncClient(transport=transport, base_url="http://bot") as client:
        yield client


@pytest.mark.asyncio
async def test_admin_ready_status(admin_client: AsyncClient) -> None:
    """Ensure the admin readiness endpoint reports an OK status."""
    response = await admin_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_admin_root_message(admin_client: AsyncClient) -> None:
    """Verify the admin landing endpoint advertises the admin APIs."""
    response = await admin_client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Admin APIs for AI Chatbot Framework"}


@pytest.mark.asyncio
async def test_bot_ready_status(bot_client: AsyncClient) -> None:
    """Confirm the bot readiness endpoint reports an OK status."""
    response = await bot_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_bot_root_message(bot_client: AsyncClient) -> None:
    """Ensure the bot root endpoint returns the welcoming message."""
    response = await bot_client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to AI Chatbot Framework API"}


def test_bot_app_has_cors_middleware() -> None:
    """Validate that the bot service retains the CORS middleware configuration."""
    assert any(middleware.cls is CORSMiddleware for middleware in bot_app.user_middleware)


def test_bot_app_mounts_static_files() -> None:
    """Ensure that the bot app exposes static assets under the expected mount path."""
    # Check for mounted apps (StaticFiles are mounted as sub-applications)
    assert any(route.path == "/static" for route in bot_app.routes if hasattr(route, 'path'))


def test_bot_channel_router_present() -> None:
    """Verify that the bot-facing channel router is registered on /bots/channels."""
    channel_routes = [route.path for route in bot_app.router.routes if route.path.startswith("/bots/channels")]
    assert channel_routes, "No routes found for /bots/channels"


@pytest.mark.asyncio
async def test_bot_lifespan_initializes_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert that the bot lifespan initializer runs and the shared DB client is closed."""

    init_called: list[bool] = []
    closed: list[bool] = []

    async def fake_init_dialogue_manager() -> None:
        init_called.append(True)

    class DummyClient:
        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr("app.main.init_dialogue_manager", fake_init_dialogue_manager)
    monkeypatch.setattr("app.main.database_client", DummyClient())

    async with _bot_lifespan(bot_app):
        assert init_called == [True]
        assert closed == []

    assert closed == [True]