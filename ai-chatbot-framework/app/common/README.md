AI Chatbot Common Package

Overview
- This package contains shared configuration and small helpers used across services.
- Primary export today is Settings (Pydantic BaseSettings) for env-driven config.

Import path
- Preferred: from ai_chatbot_common.config import Settings, get_settings
- If vendored inside the repo: from app.common import Settings, get_settings

Backwards compatibility
- Replace imports like `from app.config import app_config` with `from ai_chatbot_common.config import get_settings` and use `settings = get_settings()`.
- Keep DTOs stable; version DTOs via explicit fields and avoid breaking changes without a semver major bump.

Semver guidance
- Breaking changes to Settings fields or DTOs require a major version bump.
- Additive, backward-compatible changes are minor versions.

Packaging/Distribution
- Option 1: Publish as an internal PyPI package named ai_chatbot_common.
- Option 2: Vendor the app/common directory into each service image.

Local development
- Supports .env file in the project root; environment variables take precedence.