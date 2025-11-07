from typing import Annotated
from bson import ObjectId
from pydantic import PlainSerializer, PlainValidator

from ai_chatbot_common.config import get_settings
from app.common.database import get_mongo_client, get_db  # new preferred interfaces

ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda x: str(x), return_type=str),
    PlainValidator(lambda x: ObjectId(x)),
]

# Backwards-compatible globals while migrating to dependency-based access
settings = get_settings()
client = get_mongo_client(settings)
# Prefer database name from settings (fallback preserved via default value)
database = client.get_database(settings.MONGODB_DATABASE)