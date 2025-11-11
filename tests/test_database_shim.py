import importlib
import types
import pytest
from bson import ObjectId
from pydantic import BaseModel, ConfigDict


def test_object_id_field_serialization_and_validation():
    from app.database import ObjectIdField

    class M(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        id: ObjectIdField

    oid = ObjectId()
    m = M(id=str(oid))

    # Validation: becomes an ObjectId
    assert isinstance(m.id, ObjectId)
    assert m.id == oid

    # Serialization: dumps to str - use mode='json' to trigger serializers
    assert m.model_dump(mode='json')["id"] == str(oid)


def test_database_shim_initializes_client(monkeypatch):
    # Patch the client class used in app.common.database before importing app.database
    import app.common.database as common_db

    class FakeClient:
        def __init__(self, *a, **kw):
            self.args = a
            self.kwargs = kw

    # Ensure a fresh singleton and patched client
    monkeypatch.setattr(common_db, "_client_singleton", None, raising=False)
    monkeypatch.setattr(common_db, "AsyncIOMotorClient", FakeClient)

    # Patch Settings to avoid depending on environment
    class FakeSettings:
        MONGODB_HOST = "mongodb://shim-test:27017"
        MONGODB_DATABASE = "shimdb"

        def __init__(self):
            pass

    import app.common.config as common_config
    monkeypatch.setattr(common_config, "Settings", FakeSettings)

    # Now import (or reload) the shim module so it picks up patches
    import app.database as db_mod
    importlib.reload(db_mod)

    assert isinstance(db_mod.client, FakeClient)
    assert db_mod.database is None