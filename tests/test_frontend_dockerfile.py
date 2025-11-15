from pathlib import Path

DOCKERFILE = Path("ai-chatbot-framework/frontend/Dockerfile")


def test_dockerfile_exists():
    assert DOCKERFILE.exists(), "Frontend Dockerfile should exist at ai-chatbot-framework/frontend/Dockerfile"


def test_dockerfile_multistage_and_runtime_settings():
    src = DOCKERFILE.read_text(encoding="utf-8")
    # Multi-stage
    assert "AS deps" in src and "AS builder" in src and "AS runner" in src
    # Node base image
    assert "FROM node:18-alpine" in src
    # Build command supports npm or yarn
    assert "npm run build || yarn build" in src
    # Standalone output is copied
    assert "COPY --from=builder /usr/src/app/.next/standalone ./" in src
    assert "COPY --from=builder /usr/src/app/.next/static ./.next/static" in src
    # Next telemetry disabled and prod env
    assert "NEXT_TELEMETRY_DISABLED=1" in src
    assert "ENV NODE_ENV=production" in src
    # Exposes port 3000 and runs server.js
    assert "EXPOSE 3000" in src
    assert 'CMD ["node", "server.js"]' in src