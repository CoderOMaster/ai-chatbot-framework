from pathlib import Path
import re


BASE_PATH = Path("frontend/app/services/base.tsx")


def test_base_service_file_exists():
    assert BASE_PATH.exists(), "frontend/app/services/base.tsx should exist"


def test_base_service_uses_next_public_env_and_fallback():
    src = BASE_PATH.read_text(encoding="utf-8")
    assert "process.env.NEXT_PUBLIC_API_BASE_URL" in src, "Must use NEXT_PUBLIC_API_BASE_URL in the client"
    assert "http://localhost:8080" in src, "Should include localhost fallback for dev"


def test_api_base_url_sanitizes_trailing_slashes_and_appends_admin():
    src = BASE_PATH.read_text(encoding="utf-8")
    # ensure sanitize regex exists: replace(/\/+$/, '')
    assert "replace(/\/+$/, '')" in src, "Should strip trailing slashes from base URL"
    # Appends '/admin/' after sanitization
    assert re.search(r"API_BASE_URL\s*=\s*`\$\{baseUrl\.replace\(/\\/+\$/, ''\)\}/admin/`", src), (
        "API_BASE_URL should be composed from sanitized baseUrl and end with '/admin/'"
    )