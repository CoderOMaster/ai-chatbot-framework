"""Types that can be shared without importing database helpers."""

from __future__ import annotations

from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import PlainSerializer, PlainValidator


def validate_object_id(value):
    """Validate and convert value to ObjectId, raising ValueError for invalid inputs."""
    if isinstance(value, ObjectId):
        return value
    if value is None:
        return None
    # If it's not a string or bytes, it's likely an arbitrary type - pass it through
    if not isinstance(value, (str, bytes)):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as e:
        raise ValueError(f"Invalid ObjectId: {str(e)}")


ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda value: str(value) if isinstance(value, ObjectId) else value, return_type=str),
    PlainValidator(validate_object_id),
]