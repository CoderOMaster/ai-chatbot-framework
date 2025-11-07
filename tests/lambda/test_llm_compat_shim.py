import json

from lambda.handlers.llm import zero_shot as legacy
import lambda_handlers.llm.zero_shot as new


def test_compat_shim_delegates(monkeypatch):
    def fake_handler(event, context):
        return {"statusCode": 200, "body": json.dumps({"ok": True})}

    monkeypatch.setattr(new, "handler", fake_handler)

    event = {"text": "ping"}
    resp = legacy.handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"ok": True}