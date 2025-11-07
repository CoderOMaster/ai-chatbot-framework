import json
from lambda_handlers.webhooks import rest as rest_lambda


def test_rest_lambda_post_forwards_http(monkeypatch):
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://internal/ingest")
    monkeypatch.delenv("FORWARDING_SQS_URL", raising=False)

    forwarded = {"calls": []}

    def fake_forward(endpoint, payload, headers=None, timeout=5.0, retries=2):
        forwarded["calls"].append((endpoint, payload, headers or {}))
        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(rest_lambda, "forward_http_json", fake_forward)

    event = {
        "httpMethod": "POST",
        "body": json.dumps({"sender_id": "u1", "message": "hi", "extra": 7}),
    }
    resp = rest_lambda.handler(event, None)
    assert resp["statusCode"] == 200
    endpoint, msg, headers = forwarded["calls"][0]
    assert msg["thread_id"] == "u1"
    assert msg["text"] == "hi"
    assert msg["context"]["extra"] == 7
    assert headers["x-source"] == "rest-webhook"


def test_rest_lambda_method_not_allowed():
    event = {"httpMethod": "GET"}
    resp = rest_lambda.handler(event, None)
    assert resp["statusCode"] == 405


def test_rest_lambda_invalid_json():
    event = {"httpMethod": "POST", "body": "not-json"}
    resp = rest_lambda.handler(event, None)
    assert resp["statusCode"] == 400