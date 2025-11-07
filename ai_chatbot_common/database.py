# Thin proxy to keep a stable import path for database helpers
from app.common.database import (
    get_mongo_client,
    get_db,
    check_db_health,
    close_mongo_client,
)

__all__ = [
    "get_mongo_client",
    "get_db",
    "check_db_health",
    "close_mongo_client",
]