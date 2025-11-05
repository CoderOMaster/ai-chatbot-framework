from pathlib import Path


def test_requirements_contains_fastapi_and_psutil():
    p = Path("ai-chatbot-framework/dockerfiles/nlu-requirements.txt")
    assert p.exists()
    txt = p.read_text()
    assert "fastapi" in txt
    assert "psutil" in txt