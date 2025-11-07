from pathlib import Path


def test_dockerfile_nlu_contains_expected_defaults():
    path = Path("ai-chatbot-framework/dockerfiles/Dockerfile.nlu")
    assert path.exists()
    content = path.read_text()

    # Ensure multi-stage with deps stage and final
    assert "FROM base AS deps" in content
    assert "FROM base AS final" in content

    # Ensure it installs from wheels and sets defaults
    assert "pip wheel" in content
    assert "pip install --no-index --find-links=/wheels" in content
    assert "VOLUME [\"/models\"]" in content
    assert "uvicorn nlu_service.runtime:app" in content


def test_nlu_requirements_include_fastapi_and_psutil():
    path = Path("ai-chatbot-framework/dockerfiles/nlu-requirements.txt")
    content = path.read_text().splitlines()
    assert "fastapi" in content
    assert "uvicorn" in content
    assert "psutil" in content


def test_compose_file_has_runtime_and_trainer_services():
    path = Path("ai-chatbot-framework/docker-compose.nlu.yml")
    content = path.read_text()
    assert "nlu-runtime:" in content
    assert "nlu-trainer:" in content
    assert "MODELS_DIR=/models" in content
    assert "SPACY_LANG_MODEL=xx_core_web_sm" in content
def test_nlu_requirements_include_spacy():
    path = Path("ai-chatbot-framework/dockerfiles/nlu-requirements.txt")
    content = path.read_text().splitlines()
    assert "spacy" in content


def test_compose_env_vars_and_gpu_tag_present():
    path = Path("ai-chatbot-framework/docker-compose.nlu.yml")
    content = path.read_text()
    assert "MONGODB_HOST" in content
    assert "TRAINING_GPU_TAG" in content


def test_efs_mount_doc_mentions_models_and_spacy():
    path = Path("ai-chatbot-framework/dockerfiles/nlu-efs-mount.md")
    assert path.exists()
    txt = path.read_text()
    assert "/models" in txt
    assert "SPACY_LANG_MODEL" in txt
    assert "EFS" in txt or "S3" in txt