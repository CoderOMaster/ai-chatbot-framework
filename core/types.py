"""Types that can be shared without importing database helpers."""

from __future__ import annotations

from typing import Annotated

from bson import ObjectId
from pydantic import PlainSerializer, PlainValidator


ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda value: str(value), return_type=str),
    PlainValidator(lambda value: ObjectId(value)),
]