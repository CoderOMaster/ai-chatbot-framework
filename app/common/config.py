from __future__ import annotations
from typing import Optional
from pydantic import BaseSettings, Field
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present for local development
load_dotenv(dotenv_path=Path('.env'))

class Settings(BaseSettings):
    """
    Global application settings loaded from environment variables.
    This class is intended to be shared across services via app.common.
    """

    # Database
    MONGODB_HOST: str = Field(default="mongodb://localhost:27017", description="MongoDB connection string")
    MONGODB_DATABASE: str = Field(default="chatbot", description="MongoDB database name")

    # Auth / Security
    JWT_SECRET: str = Field(default="dev-secret", description="JWT secret for signing tokens")

    # Models / Paths
    MODELS_DIR: str = Field(default="models", description="Directory path where trained models are stored")

    # LLMs / External providers
    LLM_API_KEY: Optional[str] = Field(default=None, description="API key for LLM provider")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def __repr__(self) -> str:
        safe = self.dict()
        if safe.get("JWT_SECRET"):
            safe["JWT_SECRET"] = "***redacted***"
        if safe.get("LLM_API_KEY"):
            safe["LLM_API_KEY"] = "***redacted***"
        return f"Settings({safe})"