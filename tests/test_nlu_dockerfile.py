from pathlib import Path

DOCKERFILE = Path("ai-chatbot-framework/dockerfiles/Dockerfile.nlu")


def test_nlu_dockerfile_exists():
    assert DOCKERFILE.exists(), "NLU Dockerfile.nlu should exist"


def test_nlu_dockerfile_contents():
    src = DOCKERFILE.read_text(encoding="utf-8")

    # Multi-stage
    assert "FROM python:3.11-slim AS base" in src
    assert "FROM python:3.11-slim AS final" in src

    # Env variables
    assert "MODEL_DIR=/models" in src
    assert "SPACY_LANG_MODEL=xx_core_web_sm" in src

    # Copy app source
    assert "COPY app /app/app" in src

    # Expose port and default command to FastAPI runtime
    assert "EXPOSE 8001" in src
    assert 'CMD ["uvicorn","nlu_service.api:app"' in src

    # Attempt to ensure it tries to have spaCy model available
    assert "spacy" in src and "download" in src