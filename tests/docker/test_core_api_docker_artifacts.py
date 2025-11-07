import os


def test_core_api_dockerfile_exists_and_cmd():
    path = 'ai-chatbot-framework/Dockerfile'
    assert os.path.exists(path)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'gunicorn' in content and 'uvicorn.workers.UvicornWorker' in content
    assert 'COPY app/' in content


def test_core_api_requirements_contains_fastapi_and_gunicorn():
    path = 'ai-chatbot-framework/requirements.txt'
    assert os.path.exists(path)
    with open(path, 'r', encoding='utf-8') as f:
        txt = f.read()
    assert 'fastapi' in txt
    assert 'gunicorn' in txt
    assert 'requests' in txt


def test_core_api_docker_compose_service_present_and_env():
    path = 'ai-chatbot-framework/docker-compose.core.yml'
    assert os.path.exists(path)
    with open(path, 'r', encoding='utf-8') as f:
        yml = f.read()
    assert 'core-api:' in yml
    assert 'MODEL_FORWARDING_ENDPOINT' in yml
    assert 'nlu-runtime' in yml


def test_env_example_contains_core_envs():
    path = 'ai-chatbot-framework/.env.example'
    assert os.path.exists(path)
    with open(path, 'r', encoding='utf-8') as f:
        txt = f.read()
    for key in ['MONGODB_HOST', 'MONGODB_DATABASE', 'MODEL_FORWARDING_ENDPOINT', 'JWT_SECRET']:
        assert key in txt