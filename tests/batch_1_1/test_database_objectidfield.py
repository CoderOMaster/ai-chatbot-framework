import pytest
from bson import ObjectId
from pydantic import BaseModel, ValidationError

from app.database import ObjectIdField


class DemoModel(BaseModel):
    id: ObjectIdField


def test_objectidfield_accepts_objectid_and_serializes_to_str():
    oid = ObjectId()
    m = DemoModel(id=oid)

    # Validator should keep it as ObjectId in the model
    assert isinstance(m.id, ObjectId)
    assert m.id == oid

    # Serializer should convert to string in JSON/dump
    dumped = m.model_dump(mode="json")
    assert isinstance(dumped["id"], str)
    assert dumped["id"] == str(oid)
    assert len(dumped["id"]) == 24


def test_objectidfield_parses_hex_string_to_objectid():
    oid = ObjectId()
    m = DemoModel(id=str(oid))
    assert isinstance(m.id, ObjectId)
    assert m.id == oid


def test_objectidfield_rejects_invalid_string():
    with pytest.raises(ValidationError):
        DemoModel(id="not-a-valid-objectid")