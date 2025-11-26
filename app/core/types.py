"""Neutral core types module.

Re-export commonly used types so application modules (like schemas)
don't have to import database-specific modules directly.
"""
from app.database import ObjectIdField  # re-export for backward compatibility

__all__ = ["ObjectIdField"]