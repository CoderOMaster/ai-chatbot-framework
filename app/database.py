from typing import Annotated
from bson import ObjectId
from pydantic import PlainSerializer, PlainValidator

# Backward-compatible ObjectIdField and database access are provided here as shims.
# Prefer importing from app.common.database in new code.
from app.common.database import get_mongo_client, get_db  # noqa: F401
from app.common.config import Settings

ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda x: str(x), return_type=str),
    PlainValidator(lambda x: ObjectId(x)),
]

# Note: avoid creating client/database on import; use factory/dependency instead.
# Kept for backward compatibility if some modules still import these names.
_settings = Settings()
client = get_mongo_client(_settings)
# database is obtained lazily by callers via get_db() to respect async patterns.
database = None  # type: ignore