from pathlib import Path


def test_frontend_docker_compose_contains_service_and_env():
    path = Path("frontend/docker-compose.yml")
    assert path.exists(), "frontend/docker-compose.yml should exist"
    content = path.read_text(encoding="utf-8")

    assert "services:" in content
    assert "frontend:" in content
    assert "ports:" in content and "3000:3000" in content
    # Ensure NEXT_PUBLIC_API_BASE_URL is surfaced for local testing
    assert "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" in content