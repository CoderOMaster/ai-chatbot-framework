import json
import os
import tempfile
from types import SimpleNamespace
import importlib.util
from pathlib import Path

import pytest


def load_zero_shot_module():
    path = Path(__file__).resolve().parents[2] / "lambda" / "handlers" / "llm" / "zero_shot.py"
    spec = importlib.util.spec_from_file_location("lambda_handlers.llm.zero_shot", str(path))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


zero_shot = load_zero_shot_module()


@pytest.fixture(autouse=True)
def restore_env_and_globals(monkeypatch):
    # Ensure module-level tunables are reset between tests
    monkeypatch.setattr(zero_shot, "MAX_RETRIES", 2, raising=False)
    monkeypatch.setattr(zero_shot, "RETRY_BACKOFF_SECS", 0.01, raising=False)
    monkeypatch.setattr(zero_shot, "DEFAULT_TIMEOUT_SECS", 25, raising=False)
    yield


@pytest.fixture()
def tmp_prompt_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        tpl_name = "ZERO_SHOT_LEARNING_PROMPT.md"
        # Also patch module-level constants because they are captured at import time
        monkeypatch.setattr(zero_shot, "PROMPTS_DIR", d, raising=False)
        monkeypatch.setattr(zero_shot, "PROMPT_TEMPLATE_NAME", tpl_name, raising=False)
        # Simple template referencing intents/entities
        with open(os.path.join(d, tpl_name), "w", encoding="utf-8") as f:
            f.write("Intents: {{ intents|join(',') }}\nEntities: {{ entities|join(',') }}")
        yield d


def test_render_system_prompt_success(tmp_prompt_dir):
    out = zero_shot._render_system_prompt(["greet", "order_pizza"], ["size", "topping"])
    assert "greet" in out and "order_pizza" in out
    assert "size" in out and "topping" in out


def test_render_system_prompt_missing_template(monkeypatch, tmp_path):
    # Patch module-level constants so template cannot be found
    monkeypatch.setattr(zero_shot, "PROMPTS_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(zero_shot, "PROMPT_TEMPLATE_NAME", "MISSING.md", raising=False)
    with pytest.raises(RuntimeError) as e:
        zero_shot._render_system_prompt(["greet"], ["size"])
    assert "Prompt template not found" in str(e.value)


def test_build_chain_raises_without_client(monkeypatch, tmp_prompt_dir):
    monkeypatch.setattr(zero_shot, "ChatOpenAI", None, raising=False)
    with pytest.raises(RuntimeError) as e:
        zero_shot._build_chain(["greet"], ["size"])
    assert "LangChain/OpenAI client not available" in str(e.value)


def test_build_chain_uses_env_and_constructs_chain(monkeypatch, tmp_prompt_dir):
    # Provide env values to be consumed inside _build_chain
    monkeypatch.setenv("LLM_BASE_URL", "http://example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "abc123")
    monkeypatch.setenv("LLM_MODEL_NAME", "mymodel")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1234")
    # DEFAULT_TIMEOUT_SECS is a module constant; patch directly
    monkeypatch.setattr(zero_shot, "DEFAULT_TIMEOUT_SECS", 33, raising=False)

    created = {}

    class FakeLLM:
        def __init__(self, **kwargs):
            created["llm_kwargs"] = kwargs
        def __or__(self, other):
            return SimpleNamespace(llm=self, other=other)

    class FakePrompt:
        def __or__(self, right):
            # prompt | llm => stage
            return SimpleNamespace(llm=right)

    class FakeParser:
        pass

    def fake_from_messages(messages):
        # Ensure we do receive a system+human messages format
        assert isinstance(messages, list) and len(messages) == 2
        assert messages[0][0] == "system" and "{text}" in messages[1][1]
        return FakePrompt()

    def fake_or(left_stage, right_parser):
        # stage | parser => chain with invoke
        class FakeChain:
            def invoke(self, data):
                return {"intent": "greet", "entities": {"size": "L"}}
        return FakeChain()

    # Ensure we don't rely on real LangChain classes
    monkeypatch.setattr(zero_shot, "ChatOpenAI", FakeLLM, raising=False)
    monkeypatch.setattr(zero_shot, "ChatPromptTemplate", SimpleNamespace(from_messages=fake_from_messages), raising=False)
    monkeypatch.setattr(zero_shot, "JsonOutputParser", lambda: FakeParser(), raising=False)
    # Patch SimpleNamespace.__or__ for our stage composition
    monkeypatch.setattr(SimpleNamespace, "__or__", fake_or, raising=False)

    chain = zero_shot._build_chain(["greet"], ["size"])
    assert hasattr(chain, "invoke")

    # Verify env-driven parameters passed to ChatOpenAI
    kwargs = created["llm_kwargs"]
    assert kwargs["base_url"] == "http://example.com/v1"
    assert kwargs["api_key"] == "abc123"
    assert kwargs["model_name"] == "mymodel"
    assert kwargs["temperature"] == 0.7
    assert kwargs["extra_body"] == {"max_tokens": 1234}
    assert kwargs["timeout"] == 33


def test_invoke_with_retries_success_on_retry(monkeypatch):
    calls = {"n": 0, "sleeps": []}

    class FlakyChain:
        def invoke(self, data):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("transient")
            return {"ok": True}

    monkeypatch.setattr(zero_shot, "MAX_RETRIES", 2, raising=False)
    monkeypatch.setattr(zero_shot, "RETRY_BACKOFF_SECS", 0.05, raising=False)

    def fake_sleep(secs):
        calls["sleeps"].append(secs)

    monkeypatch.setattr(zero_shot.time, "sleep", fake_sleep)

    out = zero_shot._invoke_with_retries(FlakyChain(), "hello")
    assert out == {"ok": True}
    # Only one backoff since second attempt succeeds
    assert len(calls["sleeps"]) == 1
    assert abs(calls["sleeps"][0] - 0.05) < 1e-6


def test_invoke_with_retries_exhausts_and_raises(monkeypatch):
    class AlwaysFail:
        def invoke(self, data):
            raise ValueError("boom")

    monkeypatch.setattr(zero_shot, "MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(zero_shot, "RETRY_BACKOFF_SECS", 0.0, raising=False)

    with pytest.raises(RuntimeError) as e:
        zero_shot._invoke_with_retries(AlwaysFail(), "text")
    assert "after 2 attempts" in str(e.value)
    assert "boom" in str(e.value)


def test_parse_result_variants():
    # With intent
    out = zero_shot._parse_result({"intent": "greet", "entities": {"size": "M", "x": None}})
    assert out["intent"] == {"intent": "greet", "confidence": 1.0}
    assert out["intent_ranking"] == [{"intent": "greet", "confidence": 1.0}]
    assert out["entities"] == {"size": "M"}

    # Without intent
    out2 = zero_shot._parse_result({"entities": [1, 2]})
    assert out2["intent"] == {"intent": None, "confidence": 0.0}
    assert out2["intent_ranking"] == []
    assert out2["entities"] == {}


def test_handler_happy_path(monkeypatch):
    class FakeChain:
        def invoke(self, data):
            return {"intent": "order_pizza", "entities": {"size": "M", "extra": None}}

    monkeypatch.setattr(zero_shot, "_build_chain", lambda i, e: FakeChain())

    event = {"text": "hi", "intents": ["order_pizza"], "entities": ["size"]}
    res = zero_shot.handler(event, context=None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["intent"]["intent"] == "order_pizza"
    assert body["intent"]["confidence"] == 1.0
    assert body["entities"] == {"size": "M"}


def test_handler_missing_text():
    res = zero_shot.handler({"intents": [], "entities": []}, context=None)
    assert res["statusCode"] == 400
    assert "Missing required field: text" in res["body"]


def test_handler_invalid_types():
    res = zero_shot.handler({"text": "hi", "intents": "oops", "entities": {}}, context=None)
    assert res["statusCode"] == 400
    assert "must be lists" in res["body"]


def test_handler_internal_error(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(zero_shot, "_build_chain", boom)
    res = zero_shot.handler({"text": "hi", "intents": [], "entities": []}, context=None)
    assert res["statusCode"] == 500
    body = json.loads(res["body"])
    assert body["error"] == "LLM handler error"
    assert "kaboom" in body["detail"]