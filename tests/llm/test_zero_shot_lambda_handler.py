import json
import os
from lambda_handlers.llm.zero_shot import handler


def test_missing_text_returns_400():
    event = {"body": json.dumps({"intents": ["order_status"], "entities": ["order_id"]})}
    resp = handler(event, None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "Missing 'text'" in body["error"]


def test_direct_invoke_ok(monkeypatch):
    # Mock HTTP call fallback to avoid external requests
    from lambda_handlers.llm import zero_shot as zs

    def fake_call_http(system_prompt, user_text, base_url, api_key, model_name, temperature, max_tokens):
        assert "order_status" in system_prompt
        assert "order_id" in system_prompt
        assert user_text == "where is my order 123"
        return {"intent": "order_status", "entities": {"order_id": "123"}}

    monkeypatch.setattr(zs, "_call_with_langchain", lambda *a, **k: (_ for _ in ()).throw(Exception("no layer")))
    monkeypatch.setattr(zs, "_call_chat_completions_http", fake_call_http)

    os.environ["LLM_BASE_URL"] = "http://example.com"
    os.environ["LLM_MODEL_NAME"] = "foo"

    event = {
        "text": "where is my order 123",
        "intents": ["order_status"],
        "entities": ["order_id"],
    }
    resp = handler(event, None)
    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data == {"intent": "order_status", "entities": {"order_id": "123"}}