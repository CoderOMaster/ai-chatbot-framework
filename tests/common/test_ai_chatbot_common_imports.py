def test_common_imports_work():
    from ai_chatbot_common.config import get_settings, Settings

    s = get_settings()
    assert isinstance(s, Settings)