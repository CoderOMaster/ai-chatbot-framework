from pathlib import Path


def test_dockerfile_contains_expected_lines():
    p = Path("frontend/Dockerfile")
    assert p.exists(), "frontend/Dockerfile should exist"
    content = p.read_text()
    assert "FROM node:18-alpine AS base" in content
    assert 'CMD ["node", "server.js"]' in content
    assert "EXPOSE 3000" in content
    assert "ENV PORT=3000" in content
    # ensure build stage and runner stage are present
    assert "FROM base AS builder" in content
    assert "FROM node:18-alpine AS runner" in content