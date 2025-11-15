from typing import Annotated, Any
from bson import ObjectId
from pydantic import PlainSerializer, PlainValidator, field_serializer
from pydantic.json import pydantic_encoder

# Backward-compatible ObjectIdField and database access are provided here as shims.
# Prefer importing from app.common.database in new code.
from app.common.database import get_mongo_client, get_db  # noqa: F401
from app.common.config import Settings

def serialize_object_id(obj: ObjectId, _info) -> str:
    """Custom serializer for ObjectId that works with JSON mode."""
    return str(obj)

ObjectIdField = Annotated[
    ObjectId,
    PlainValidator(lambda x: ObjectId(x) if not isinstance(x, ObjectId) else x),
    PlainSerializer(serialize_object_id, return_type=str, when_used='json'),
]

# Note: avoid creating client/database on import; use factory/dependency instead.
# Kept for backward compatibility if some modules still import these names.
_settings = Settings()
client = get_mongo_client(_settings)
# database is obtained lazily by callers via get_db() to respect async patterns.
database = None  # type: ignore