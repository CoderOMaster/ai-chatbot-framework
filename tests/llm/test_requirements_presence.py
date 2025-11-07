from pathlib import Path

def test_llm_lambda_requirements_include_jinja2():
    req = Path('lambda_handlers/llm/requirements.txt').read_text().lower()
    assert 'jinja2' in req


def test_llm_layer_requirements_file_exists():
    assert Path('lambda/handlers/llm/layer/requirements.txt').exists()