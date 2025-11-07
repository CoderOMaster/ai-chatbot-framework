def test_ai_chatbot_common_webhooks_exports():
    # Ensure symbols are exported from package root for stable imports
    from ai_chatbot_common import verify_facebook_signature, forward_http_json, send_to_sqs  # noqa: F401

    assert callable(verify_facebook_signature)
    assert callable(forward_http_json)
    assert callable(send_to_sqs)