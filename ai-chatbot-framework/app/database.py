from typing import Annotated
from bson import ObjectId
from pydantic import PlainSerializer, PlainValidator

# Keep ObjectIdField for existing models
ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda x: str(x), return_type=str),
    PlainValidator(lambda x: ObjectId(x)),
]

# Deprecated: direct client/database creation moved to ai_chatbot_common.database
# Import helpers to provide compatibility shims if needed by legacy code
try:
    from ai_chatbot_common.database import get_db, get_mongo_client, db_dependency  # type: ignore
except Exception:  # pragma: no cover - in case common module not available in some env
    get_db = None  # type: ignore
    get_mongo_client = None  # type: ignore
    db_dependency = None  # type: ignore