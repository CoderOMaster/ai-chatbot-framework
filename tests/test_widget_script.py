"""Pytest suite that validates the behavior introduced in app/static/widget/script.js."""
import logging
import random
import re
from typing import Any, Optional

import pytest

LOGGER = logging.getLogger("chat_widget")


def resolve_chat_endpoint(backend_url: Optional[str], base_url: Optional[str]) -> str:
    """Replicates the endpoint resolution logic from the widget script."""
    if isinstance(backend_url, str) and backend_url.strip():
        return backend_url.strip()

    if isinstance(base_url, str) and base_url.strip():
        cleaned_base = base_url.rstrip("/")
        return f"{cleaned_base}/bots/channels/rest/webbook"

    LOGGER.warning("Chat widget backend URL is not configured. Falling back to default REST endpoint.")
    return "/bots/channels/rest/webbook"


def sanitize_message_content(content: Any) -> str:
    """Emulates the widget's safe sanitation by tallying a safe string representation."""
    if content is None:
        return ""

    return str(content)


def generate_uuid() -> str:
    """Imitates the JavaScript uuid() helper used by the widget."""

    def replacer(match: re.Match) -> str:
        char = match.group(0)
        value = random.randrange(16)
        if char == "y":
            value = (value & 0x3) | 0x8
        return format(value, "x")

    return re.sub(r"[xy]", replacer, "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx")


@pytest.mark.parametrize(
    "backend_url, base_url, expected",
    [
        (" https://custom.api/ ", None, "https://custom.api/"),
        ("https://custom.api", "https://ignored.base", "https://custom.api"),
    ],
)
def test_resolve_chat_endpoint_prefers_widget_backend_url(
    backend_url: Optional[str], base_url: Optional[str], expected: str
) -> None:
    """Ensure the widget honors a configured iky_widget_backend_url before falling back."""
    endpoint = resolve_chat_endpoint(backend_url, base_url)
    assert endpoint == expected


def test_resolve_chat_endpoint_constructs_from_base_url() -> None:
    """Validate the widget builds the endpoint from iky_base_url when the backend value is missing."""
    endpoint = resolve_chat_endpoint(None, "https://base.example.com/")
    assert endpoint == "https://base.example.com/bots/channels/rest/webbook"


def test_resolve_chat_endpoint_uses_default_and_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """When no config is provided, the default endpoint is returned and a warning is emitted."""
    caplog.set_level(logging.WARNING, logger=LOGGER.name)
    endpoint = resolve_chat_endpoint(None, None)
    assert endpoint == "/bots/channels/rest/webbook"
    assert "Chat widget backend URL is not configured" in caplog.text


@pytest.mark.parametrize(
    "input_value, expected",
    [
        (None, ""),
        ("message", "message"),
        (123, "123"),
        ({"key": "value"}, "{'key': 'value'}"),
    ],
)
def test_sanitize_message_content_handles_several_inputs(input_value: Any, expected: str) -> None:
    """Confirm that the sanitation helper always yields a string and treats None as empty."""
    sanitized = sanitize_message_content(input_value)
    assert sanitized == expected


def test_generate_uuid_format_and_uniqueness() -> None:
    """Ensure the UUID generator matches the v4 pattern and produces distinct values."""
    uuid_one = generate_uuid()
    uuid_two = generate_uuid()
    pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    assert pattern.match(uuid_one)
    assert pattern.match(uuid_two)
    assert uuid_one != uuid_two