AI Chatbot Common Package

Overview
- This package centralizes shared configuration and small helpers used across services.
- Import using the stable namespace:
  from ai_chatbot_common.config import Settings, get_settings

Backwards compatibility
- app.config.app_config continues to exist as a thin shim over Settings for now.
- Prefer migrating all imports from `from app.config import ...` to
  `from ai_chatbot_common.config import Settings, get_settings`.

Semantic versioning
- Public surface: Settings fields and helper functions are versioned using SemVer.
- Non-breaking changes: adding new optional fields.
- Breaking changes: renaming/removing fields or changing types. Bump MAJOR version.

Local development
- Settings reads from environment variables and supports a local .env file.

Packaging/Distribution
- This folder can be vendored or packaged as `ai_chatbot_common`.
- In service Docker builds, ensure this folder is copied into the image
  and install runtime requirements (pydantic-settings).