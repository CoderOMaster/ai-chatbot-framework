import pytest
import asyncio
from types import SimpleNamespace
from bson import ObjectId
from pymongo.errors import PyMongoError

import app.database as database


# Test ObjectIdField validation for ObjectId instance

def test_objectidfield_validate_with_objectid():
    oid = ObjectId()
    val = database.ObjectIdField.validate(oid)
    assert isinstance(val, str)
    assert val == str(oid)


# Test ObjectIdField validation for string

def test_objectidfield_validate_with_string():
    s = "507f1f77bcf86cd799439011"
    val = database.ObjectIdField.validate(s)
    assert val == s


# Test Mongo client creation with monkeypatching AsyncIOMotorClient

def test_build_mongo_uri_and_client(monkeypatch):
    FakeClientCreated = {}

    class FakeClient:
        def __init__(self, uri, **kwargs):
            FakeClientCreated['uri'] = uri
            FakeClientCreated['kwargs'] = kwargs

    # Added missing attrs MONGODB_USERNAME and MONGODB_PASSWORD to settings
    settings = SimpleNamespace(
        MONGODB_HOST="localhost",
        MONGODB_MAX_POOL_SIZE=10,
        MONGODB_CONNECT_TIMEOUT_MS=2000,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=3000,
        MONGODB_DATABASE='testdb',
        MONGODB_USERNAME=None,
        MONGODB_PASSWORD=None
    )

    monkeypatch.setattr(database, "_client_singleton", None)
    monkeypatch.setattr("motor.motor_asyncio.AsyncIOMotorClient", FakeClient)

    client = database.get_mongo_client(settings)
    print(f'Client class: {client.__class__}')
    # The returned client is a FakeClient instance due to monkeypatch
    assert isinstance(client, FakeClient)
    assert FakeClientCreated['uri'] == "mongodb://localhost:27017"
    assert 'maxPoolSize' in FakeClientCreated['kwargs']


# Async test for check_db_connection retry logic
@pytest.mark.asyncio
async def test_check_db_connection_retries(monkeypatch):
    calls = {"count": 0}

    class FakeDB:
        def __init__(self, fail_then_succeed=1):
            self.fail_then_succeed = fail_then_succeed

        async def command(self, cmd):
            calls['count'] += 1
            if calls['count'] <= 1:
                raise PyMongoError("transient")
            return {"ok": 1}

    fake_db = FakeDB()

    # avoid real sleep
    async def fake_sleep(x):
        return None

    monkeypatch.setattr(database.asyncio, "sleep", fake_sleep)

    ok = await database.check_db_connection(fake_db, retries=2, backoff_factor=0.01)
    assert ok is True
    assert calls['count'] >= 2