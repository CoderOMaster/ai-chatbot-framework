app.common - Shared configuration and helpers

Overview
- This package centralizes shared configuration (Settings) and small DI/factory helpers to be used by multiple services.

Importing
- Preferred: from app.common.config import Settings
- Backwards compatible pattern to migrate from: from app.config import X -> replace with Settings().X

SemVer and stability
- DTOs and Settings fields should be versioned deliberately. Additive changes are minor, breaking changes require a major version bump.

Packaging/Distribution
- If publishing as a library, include app/common in your package data. Alternatively, vendor this folder into each service image during the Docker build stage.

Local usage
- Settings loads from environment variables and optional .env file.
- Example: from app.common.config import Settings; settings = Settings(); print(settings.MODELS_DIR)
Database utilities
- Use app.common.database.get_db() in async contexts to obtain an AsyncIOMotorDatabase.
- Configure via environment variables in app/common/.env.example.
- Health check helper: app.common.database.ping_db() with retries/backoff.