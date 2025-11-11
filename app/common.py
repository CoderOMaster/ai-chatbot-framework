import os
from typing import Optional


class Settings:
    """Application settings configuration."""
    
    def __init__(self):
        self.MODELS_DIR: str = os.getenv("MODELS_DIR", "models")
    
    @property
    def models_dir(self) -> str:
        """Get the models directory path."""
        return self.MODELS_DIR