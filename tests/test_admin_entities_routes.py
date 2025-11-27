import pytest
from types import SimpleNamespace
from typing import Any, Dict, List

from fastapi import HTTPException

import app.admin.entities.routes as routes


class DummyEntity:
    """Simple stand-in for Pydantic model with model_dump()."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def model_dump(self) -> Dict[str, Any]:
        return self._data


@pytest.mark.asyncio
async def test_get_user_id_with_id() -> None:
    """get_user_id should return the 'id' field when present."""
    user = {"id": "user-1"}
    result = await routes.get_user_id(current_user=user)
    assert result == "user-1"


@pytest.mark.asyncio
async def test_get_user_id_with_sub() -> None:
    """get_user_id should fall back to 'sub' when 'id' is absent."""
    user = {"sub": "user-2"}
    result = await routes.get_user_id(current_user=user)
    assert result == "user-2"


@pytest.mark.asyncio
async def test_get_user_id_missing() -> None:
    """get_user_id should raise HTTPException 401 when no id/sub present."""
    with pytest.raises(HTTPException) as exc:
        await routes.get_user_id(current_user={})
    assert exc.value.status_code == 401


# create_entity tests
@pytest.mark.asyncio
async def test_create_entity_success(monkeypatch) -> None:
    """create_entity should call store.add_entity and return created entity."""

    async def mock_add_entity(entity_dict, user_id=None):
        return SimpleNamespace(id="e1", **entity_dict)

    monkeypatch.setattr(routes.store, "add_entity", mock_add_entity)

    dummy = DummyEntity({"name": "Test"})
    created = await routes.create_entity(dummy, user_id="user-x")
    assert hasattr(created, "id") and created.id == "e1"
    assert created.name == "Test"


@pytest.mark.asyncio
async def test_create_entity_value_error(monkeypatch) -> None:
    """create_entity should return HTTP 400 when store.add_entity raises ValueError."""

    async def mock_add_entity(entity_dict, user_id=None):
        raise ValueError("invalid input")

    monkeypatch.setattr(routes.store, "add_entity", mock_add_entity)

    dummy = DummyEntity({"name": "Bad"})
    with pytest.raises(HTTPException) as exc:
        await routes.create_entity(dummy, user_id="u")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_entity_exception(monkeypatch) -> None:
    """create_entity should return HTTP 500 on unexpected exceptions."""

    async def mock_add_entity(entity_dict, user_id=None):
        raise Exception("boom")

    monkeypatch.setattr(routes.store, "add_entity", mock_add_entity)

    dummy = DummyEntity({"name": "Err"})
    with pytest.raises(HTTPException) as exc:
        await routes.create_entity(dummy, user_id="u")
    assert exc.value.status_code == 500


# read_entities tests
@pytest.mark.asyncio
async def test_read_entities_success(monkeypatch) -> None:
    """read_entities should return paginated data and correct totals."""

    sample_entities = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]

    async def mock_list_entities(page, page_size, sort_by, sort_order, name_filter):
        return sample_entities, 2

    monkeypatch.setattr(routes.store, "list_entities", mock_list_entities)

    result = await routes.read_entities(page=1, page_size=50, sort_by="created_at", sort_order="desc", name_filter=None, user_id="u1")
    assert "data" in result and "pagination" in result
    assert result["data"] == sample_entities
    assert result["pagination"]["total_count"] == 2


@pytest.mark.asyncio
async def test_read_entities_invalid_sort_by() -> None:
    """read_entities should reject invalid sort_by values with HTTP 400."""
    with pytest.raises(HTTPException) as exc:
        await routes.read_entities(page=1, page_size=10, sort_by="invalid_field", sort_order="asc", name_filter=None, user_id="u")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_read_entities_list_value_error(monkeypatch) -> None:
    """If store.list_entities raises ValueError, endpoint returns HTTP 400."""

    async def mock_list_entities(*args, **kwargs):
        raise ValueError("bad query")

    monkeypatch.setattr(routes.store, "list_entities", mock_list_entities)

    with pytest.raises(HTTPException) as exc:
        await routes.read_entities(user_id="u")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_read_entities_list_exception(monkeypatch) -> None:
    """If store.list_entities raises generic Exception, endpoint returns HTTP 500."""

    async def mock_list_entities(*args, **kwargs):
        raise Exception("db down")

    monkeypatch.setattr(routes.store, "list_entities", mock_list_entities)

    with pytest.raises(HTTPException) as exc:
        await routes.read_entities(user_id="u")
    assert exc.value.status_code == 500


# read_entity tests
@pytest.mark.asyncio
async def test_read_entity_success(monkeypatch) -> None:
    """read_entity should return entity when found."""

    async def mock_get_entity(entity_id):
        return SimpleNamespace(id=entity_id, name="X")

    monkeypatch.setattr(routes.store, "get_entity", mock_get_entity)

    ent = await routes.read_entity("ent-1", user_id="u")
    assert ent.id == "ent-1"
    assert ent.name == "X"


@pytest.mark.asyncio
async def test_read_entity_not_found(monkeypatch) -> None:
    """read_entity should return HTTP 404 when store.get_entity raises ValueError."""

    async def mock_get_entity(entity_id):
        raise ValueError("not found")

    monkeypatch.setattr(routes.store, "get_entity", mock_get_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.read_entity("missing", user_id="u")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_read_entity_exception(monkeypatch) -> None:
    """read_entity should return HTTP 500 on unexpected exceptions."""

    async def mock_get_entity(entity_id):
        raise Exception("boom")

    monkeypatch.setattr(routes.store, "get_entity", mock_get_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.read_entity("ent", user_id="u")
    assert exc.value.status_code == 500


# update_entity tests
@pytest.mark.asyncio
async def test_update_entity_success(monkeypatch) -> None:
    """update_entity should return updated entity on success."""

    async def mock_edit_entity(entity_id, entity_dict, user_id=None):
        return SimpleNamespace(id=entity_id, **entity_dict)

    monkeypatch.setattr(routes.store, "edit_entity", mock_edit_entity)

    dummy = DummyEntity({"name": "Updated"})
    updated = await routes.update_entity("e-1", dummy, user_id="u")
    assert updated.id == "e-1"
    assert updated.name == "Updated"


@pytest.mark.asyncio
async def test_update_entity_not_found(monkeypatch) -> None:
    """update_entity should map ValueError with 'not found' to HTTP 404."""

    async def mock_edit_entity(*args, **kwargs):
        raise ValueError("Entity not found")

    monkeypatch.setattr(routes.store, "edit_entity", mock_edit_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.update_entity("e-404", DummyEntity({}), user_id="u")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_entity_validation_error(monkeypatch) -> None:
    """update_entity should map other ValueError to HTTP 400."""

    async def mock_edit_entity(*args, **kwargs):
        raise ValueError("invalid update")

    monkeypatch.setattr(routes.store, "edit_entity", mock_edit_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.update_entity("e-1", DummyEntity({}), user_id="u")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_entity_exception(monkeypatch) -> None:
    """update_entity should return HTTP 500 on unexpected exceptions."""

    async def mock_edit_entity(*args, **kwargs):
        raise Exception("ouch")

    monkeypatch.setattr(routes.store, "edit_entity", mock_edit_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.update_entity("e-1", DummyEntity({}), user_id="u")
    assert exc.value.status_code == 500


# delete_entity tests
@pytest.mark.asyncio
async def test_delete_entity_success(monkeypatch) -> None:
    """delete_entity should not raise when deletion succeeds."""

    async def mock_delete_entity(entity_id, user_id=None):
        return None

    monkeypatch.setattr(routes.store, "delete_entity", mock_delete_entity)

    # Should not raise
    await routes.delete_entity("to-delete", user_id="u")


@pytest.mark.asyncio
async def test_delete_entity_not_found(monkeypatch) -> None:
    """delete_entity should return HTTP 404 when entity missing."""

    async def mock_delete_entity(entity_id, user_id=None):
        raise ValueError("not found")

    monkeypatch.setattr(routes.store, "delete_entity", mock_delete_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.delete_entity("missing", user_id="u")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_entity_exception(monkeypatch) -> None:
    """delete_entity should return HTTP 500 on unexpected exceptions."""

    async def mock_delete_entity(entity_id, user_id=None):
        raise Exception("bad")

    monkeypatch.setattr(routes.store, "delete_entity", mock_delete_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.delete_entity("id", user_id="u")
    assert exc.value.status_code == 500


# restore_entity tests
@pytest.mark.asyncio
async def test_restore_entity_success(monkeypatch) -> None:
    """restore_entity should return restored entity on success."""

    async def mock_restore_entity(entity_id, user_id=None):
        return SimpleNamespace(id=entity_id, restored=True)

    monkeypatch.setattr(routes.store, "restore_entity", mock_restore_entity)

    res = await routes.restore_entity("r1", user_id="u")
    assert res.id == "r1"
    assert getattr(res, "restored") is True


@pytest.mark.asyncio
async def test_restore_entity_not_found(monkeypatch) -> None:
    """restore_entity should return HTTP 404 when not found."""

    async def mock_restore_entity(entity_id, user_id=None):
        raise ValueError("not found")

    monkeypatch.setattr(routes.store, "restore_entity", mock_restore_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.restore_entity("x", user_id="u")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_restore_entity_bad_request(monkeypatch) -> None:
    """restore_entity should return HTTP 400 for other ValueError cases."""

    async def mock_restore_entity(entity_id, user_id=None):
        raise ValueError("already active")

    monkeypatch.setattr(routes.store, "restore_entity", mock_restore_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.restore_entity("x", user_id="u")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_restore_entity_exception(monkeypatch) -> None:
    """restore_entity should return HTTP 500 on unexpected exceptions."""

    async def mock_restore_entity(entity_id, user_id=None):
        raise Exception("err")

    monkeypatch.setattr(routes.store, "restore_entity", mock_restore_entity)

    with pytest.raises(HTTPException) as exc:
        await routes.restore_entity("x", user_id="u")
    assert exc.value.status_code == 500


# bulk_import_entities tests
@pytest.mark.asyncio
async def test_bulk_import_entities_success(monkeypatch) -> None:
    """bulk_import_entities should return created ids and count on success."""

    async def mock_bulk_import_entities(entity_dicts: List[Dict[str, Any]], user_id=None):
        return ["id1", "id2"]

    monkeypatch.setattr(routes.store, "bulk_import_entities", mock_bulk_import_entities)

    entities = [DummyEntity({"name": "a"}), DummyEntity({"name": "b"})]
    res = await routes.bulk_import_entities(entities, user_id="u")
    assert res["created_count"] == 2
    assert res["created_ids"] == ["id1", "id2"]


@pytest.mark.asyncio
async def test_bulk_import_entities_empty() -> None:
    """bulk_import_entities should return HTTP 400 when called with empty list."""
    with pytest.raises(HTTPException) as exc:
        await routes.bulk_import_entities([], user_id="u")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_bulk_import_entities_too_many() -> None:
    """bulk_import_entities should return HTTP 400 when too many entities provided."""
    many = [DummyEntity({}) for _ in range(1001)]
    with pytest.raises(HTTPException) as exc:
        await routes.bulk_import_entities(many, user_id="u")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_bulk_import_entities_store_exception(monkeypatch) -> None:
    """bulk_import_entities should return HTTP 500 on unexpected store errors."""

    async def mock_bulk_import_entities(entity_dicts, user_id=None):
        raise Exception("fail")

    monkeypatch.setattr(routes.store, "bulk_import_entities", mock_bulk_import_entities)

    entities = [DummyEntity({"name": "a"})]
    with pytest.raises(HTTPException) as exc:
        await routes.bulk_import_entities(entities, user_id="u")
    assert exc.value.status_code == 500


# get_audit_log tests
@pytest.mark.asyncio
async def test_get_audit_log_success(monkeypatch) -> None:
    """get_audit_log should return entries and count on success."""

    async def mock_get_audit_log(entity_id=None, action=None, limit=100):
        return [{"id": "log1"}, {"id": "log2"}]

    monkeypatch.setattr(routes.store, "get_audit_log", mock_get_audit_log)

    res = await routes.get_audit_log(entity_id=None, action=None, limit=10, user_id="u")
    assert res["count"] == 2
    assert len(res["entries"]) == 2


@pytest.mark.asyncio
async def test_get_audit_log_exception(monkeypatch) -> None:
    """get_audit_log should return HTTP 500 on unexpected exceptions."""

    async def mock_get_audit_log(*args, **kwargs):
        raise Exception("boom")

    monkeypatch.setattr(routes.store, "get_audit_log", mock_get_audit_log)

    with pytest.raises(HTTPException) as exc:
        await routes.get_audit_log(entity_id=None, action=None, limit=10, user_id="u")
    assert exc.value.status_code == 500