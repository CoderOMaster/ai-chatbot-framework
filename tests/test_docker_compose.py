from pathlib import Path


def test_docker_compose_has_service_and_env():
    p = Path("frontend/docker-compose.yml")
    assert p.exists(), "frontend/docker-compose.yml should exist"
    content = p.read_text()
    assert "version: '3.8'" in content
    assert "services:" in content
    assert "frontend:" in content
    assert "ports:" in content and "\"3000:3000\"" in content
    assert "NEXT_PUBLIC_API_BASE_URL" in content