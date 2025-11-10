from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Runtime configuration for AI Chatbot services.

    Values are loaded from environment variables. A local .env file is also
    supported for developer convenience.

    Example envs:
      - MONGODB_HOST=mongodb://localhost:27017
      - MONGODB_DATABASE=chatbot
      - JWT_SECRET=supersecret
      - LLM_API_KEY=...
      - MODELS_DIR=./models
    """

    # Database
    MONGODB_HOST: str = Field(..., description="MongoDB connection string")
    MONGODB_DATABASE: str = Field(..., description="MongoDB database name")

    # Auth/security
    JWT_SECRET: str = Field(..., description="Secret for signing JWT tokens")

    # LLM and external providers
    LLM_API_KEY: Optional[str] = Field(None, description="API key for LLM provider")

    # Models path
    MODELS_DIR: str = Field("./models", description="Directory path for NLU models")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Use this as a dependency in FastAPI or as a simple factory in scripts.
    """
    return Settings()