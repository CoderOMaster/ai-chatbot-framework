import pathlib


def test_core_api_requirements_contains_runtime_libs():
    p = pathlib.Path("ai-chatbot-framework/requirements.txt")
    assert p.is_file()
    txt = p.read_text(encoding="utf-8").lower()
    for pkg in ("fastapi", "uvicorn", "motor", "pydantic", "aiohttp", "jinja2"):
        assert pkg in txt