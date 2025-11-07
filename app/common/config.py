from functools import lru_cache
from typing import Optional
from pydantic import Field
try:
    # Pydantic v2 uses pydantic-settings
    from pydantic_settings import BaseSettings, SettingsConfigDict
except Exception:  # pragma: no cover - fallback if pydantic-settings absent
    from pydantic import BaseModel as BaseSettings  # type: ignore
    SettingsConfigDict = dict  # type: ignore


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    Uses pydantic-settings for robust env parsing.
    Supports loading a local .env file for development.
    """

    # Database
    MONGODB_HOST: str = Field(default="mongodb://127.0.0.1:27017", description="MongoDB connection string")
    MONGODB_DATABASE: str = Field(default="ai-chatbot-framework", description="MongoDB database name")
    MONGODB_USERNAME: Optional[str] = Field(default=None, description="MongoDB username", repr=False)
    MONGODB_PASSWORD: Optional[str] = Field(default=None, description="MongoDB password", repr=False)
    MONGODB_MAX_POOL_SIZE: int = Field(default=100, description="Max pool size for Mongo client")
    MONGODB_CONNECT_TIMEOUT_MS: int = Field(default=2000, description="Connect timeout in ms")
    MONGODB_SERVER_SELECTION_TIMEOUT_MS: int = Field(default=2000, description="Server selection timeout in ms")
    MONGODB_HEALTHCHECK_ENABLED: bool = Field(default=True, description="Enable DB health checks")

    # App model directories and names
    MODELS_DIR: str = Field(default="model_files/", description="Directory where trained models are stored")
    DEFAULT_FALLBACK_INTENT_NAME: str = Field(default="fallback")
    DEFAULT_WELCOME_INTENT_NAME: str = Field(default="init_conversation")

    # NLP
    SPACY_LANG_MODEL: str = Field(default="en_core_web_md")

    # Security / external services
    JWT_SECRET: Optional[str] = Field(default=None)
    LLM_API_KEY: Optional[str] = Field(default=None)

    # Framework / environment flags
    DEBUG: bool = Field(default=False)
    DEVELOPMENT: bool = Field(default=True)

    # pydantic-settings config
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    The cache ensures a single source of truth per process and avoids ad-hoc
    global singletons. Override by clearing the cache in tests if necessary.
    """
    return Settings()  # type: ignore[call-arg]