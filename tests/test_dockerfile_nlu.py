from pathlib import Path


def test_dockerfile_contains_uvicorn_and_modeldir():
    p = Path("ai-chatbot-framework/dockerfiles/Dockerfile.nlu")
    assert p.exists()
    txt = p.read_text()
    # Adjusted assertion to check for uvicorn command elements in list format since CMD in Dockerfile is JSON array
    assert 'CMD ["uvicorn", "nlu_service.api:app", "--host", "0.0.0.0", "--port", "8001"]' in txt
    assert "MODEL_DIR" in txt