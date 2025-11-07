import re
from pathlib import Path


def read(p):
    return Path(p).read_text(encoding="utf-8")


def test_widget_resolves_api_base_url_fallbacks_and_sets_global():
    js = read("app/static/widget/script.js")
    # resolveBaseUrl function exists
    assert "function resolveBaseUrl()" in js
    # Fallback order: window.iky_base_url -> data attribute -> window.location.origin + '/api'
    assert "window.iky_base_url" in js
    assert "data-api-base-url" in js
    assert "/api`" in js or "/api'" in js or "/api\"" in js

    # API_BASE variable and it populates window.iky_base_url if missing
    assert re.search(r"const\s+API_BASE\s*=\s*resolveBaseUrl\(\)\s*;", js)
    assert re.search(r"if\s*\(!window\\.iky_base_url\)\s*\{\s*\n\s*window\\.iky_base_url\s*=\s*API_BASE;", js)


def test_widget_uses_rest_webhook_endpoint_for_requests():
    js = read("app/static/widget/script.js")
    # Ensure the widget posts to the REST webhook endpoint
    # Expect '/bots/channels/rest/webhook' (note: 'webhook' not 'webbook')
    assert "/bots/channels/rest/webhook" in js, "Widget should call the REST webhook endpoint at /bots/channels/rest/webhook"
    assert "webbook" not in js, "Typo detected: found 'webbook' in endpoint path; should be 'webhook'"


def test_widget_initializes_on_window_load():
    js = read("app/static/widget/script.js")
    assert "window.addEventListener('load'" in js or 'window.addEventListener("load"' in js
    assert "new ChatWidget()" in js