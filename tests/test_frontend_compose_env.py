from pathlib import Path

COMPOSE = Path("ai-chatbot-framework/frontend/docker-compose.yml")


def test_compose_file_exists():
    assert COMPOSE.exists(), "docker-compose.yml for frontend should exist"


def test_compose_exposes_port_and_env_var():
    src = COMPOSE.read_text(encoding="utf-8")
    # Port mapping 3000:3000
    assert "3000:3000" in src
    # NEXT_PUBLIC_API_BASE_URL environment variable present and points to localhost:8000
    assert "NEXT_PUBLIC_API_BASE_URL" in src
    assert "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" in src