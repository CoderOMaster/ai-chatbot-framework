from pathlib import Path


def test_docker_compose_has_service_nlu_runtime():
    p = Path("ai-chatbot-framework/docker-compose.nlu.yml")
    assert p.exists()
    txt = p.read_text()
    assert "nlu-runtime" in txt