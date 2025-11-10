import pathlib


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_core_api_dockerfile_exposes_and_cmd():
    dockerfile = read("ai-chatbot-framework/Dockerfile")
    assert "EXPOSE 8000" in dockerfile
    assert "gunicorn" in dockerfile
    assert "app.main:app" in dockerfile


def test_core_api_compose_env_and_deps():
    compose = read("ai-chatbot-framework/docker-compose.core.yml")
    # Service exists and maps port
    assert "core-api" in compose and "8000:8000" in compose
    # Environment variables set for db and model forwarding
    assert "MONGODB_HOST" in compose
    assert "MONGODB_DATABASE" in compose
    assert "MODEL_FORWARDING_ENDPOINT" in compose
    # Depends on mongodb and nlu-runtime
    assert "depends_on" in compose
    assert "mongodb" in compose and "nlu-runtime" in compose