from pathlib import Path
import re


def test_widget_script_contains_chatwidget_and_methods():
    p = Path("app/static/widget/script.js")
    assert p.exists(), "app/static/widget/script.js should exist"
    content = p.read_text()

    # Basic class and lifecycle
    assert "class ChatWidget" in content
    assert "new ChatWidget()" in content or "new ChatWidget" in content

    # Methods
    for method in ["createElements", "attachEventListeners", "toggleChat", "addMessage", "showTyping", "hideTyping", "initChat", "sendMessage"]:
        assert method + "(" in content, f"Expected method {method} in script.js"

    # Ensure addMessage uses innerHTML (was intentionally changed to render HTML)
    assert "innerHTML = content" in content or "message.innerHTML = content" in content

    # Ensure fetch endpoints reference the rest webhook
    assert "/bots/channels/rest/webbook" in content or "/bots/channels/rest/webhook" in content

    # Ensure typing indicator markup exists
    assert "iky-typing-dot" in content

    # Ensure base URL resolution uses iky_base_url or window.location.origin
    assert "window.iky_base_url" in content or "window.location.origin" in content