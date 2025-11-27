import pytest
import asyncio
from types import SimpleNamespace
from datetime import datetime

import app.admin.intents.routes as routes


class DummyIntentObj:
    def __init__(self, data: dict):
        # allow attribute access for relatedIntents, status, etc.
        for k, v in data.items():
            setattr(self, k, v)


class DummyIntentInput:
    def __init__(self, data: dict):
        self._data = data

    def model_dump(self, exclude=None):
        # mimic pydantic model_dump
        return {k: v for k, v in self._data.items() if not (exclude and k in exclude)}


class DummyUser:
    def __init__(self, id: str = "user-1"):
        self.id = id


@pytest.mark.asyncio
async def test_validate_circular_references_no_related():
    """_validate_circular_references should pass when no relatedIntents provided"""
    data = {"name": "Test", "relatedIntents": []}
    # Should not raise
    await routes._validate_circular_references(data)


@pytest.mark.asyncio
async def test_validate_circular_references_self_reference_raises():
    """_validate_circular_references should raise when intent references itself"""
    data = {"relatedIntents": ["intent-1"]}
    with pytest.raises(routes.CircularReferenceError):
        await routes._validate_circular_references(data, intent_id="intent-1")


@pytest.mark.asyncio
async def test_validate_circular_references_detects_cycle(monkeypatch):
    """Detect circular chain A -> B -> A and raise CircularReferenceError"""
    # intent_id is B, relatedIntents of new intent contains A
    data = {"relatedIntents": ["A"]}

    async def fake_get_intent(id: str):
        if id == "A":
            return SimpleNamespace(relatedIntents=["B"])  # A -> B
        if id == "B":
            return SimpleNamespace(relatedIntents=["A"])  # B -> A
        raise routes.IntentNotFoundError("not found")

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)

    with pytest.raises(routes.CircularReferenceError):
        await routes._validate_circular_references(data, intent_id="B")


@pytest.mark.asyncio
async def test_validate_circular_references_ignores_missing_intent(monkeypatch):
    """If a related intent cannot be found, it should be ignored (no exception)."""
    data = {"relatedIntents": ["missing"]}

    async def fake_get_intent(id: str):
        raise routes.IntentNotFoundError("not found")

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)

    # Should not raise
    await routes._validate_circular_references(data)


@pytest.mark.asyncio
async def test_create_intent_success(monkeypatch):
    """create_intent should call add_intent and return created intent"""
    input_data = {"name": "NewIntent", "relatedIntents": []}
    dummy_intent = DummyIntentInput(input_data)
    user = DummyUser("creator-1")

    async def fake_add_intent(intent_dict):
        assert intent_dict["created_by"] == "creator-1"
        assert intent_dict["status"] == "draft"
        return SimpleNamespace(**{**intent_dict, "id": "new-1"})

    monkeypatch.setattr(routes.store, "add_intent", fake_add_intent)
    # Ensure validation passes
    monkeypatch.setattr(routes, "_validate_circular_references", lambda *_: asyncio.sleep(0))

    created = await routes.create_intent(dummy_intent, current_user=user)
    assert getattr(created, "id") == "new-1"
    assert getattr(created, "created_by") == "creator-1"
    assert getattr(created, "status") == "draft"


@pytest.mark.asyncio
async def test_create_intent_circular_validation_failure(monkeypatch):
    """create_intent should return HTTP 400 when circular validation fails"""
    dummy_intent = DummyIntentInput({"name": "X"})
    user = DummyUser()

    async def raise_circular(*args, **kwargs):
        raise routes.CircularReferenceError("cycle")

    monkeypatch.setattr(routes, "_validate_circular_references", raise_circular)

    with pytest.raises(Exception) as exc:
        await routes.create_intent(dummy_intent, current_user=user)
    assert "Circular reference validation failed" in str(exc.value)


@pytest.mark.asyncio
async def test_read_intents_success(monkeypatch):
    """read_intents should return paginated data"""
    async def fake_list_intents(skip, limit, search, filters):
        return ([SimpleNamespace(id="1", name="a")], 1)

    monkeypatch.setattr(routes.store, "list_intents", fake_list_intents)

    res = await routes.read_intents(skip=0, limit=10, search=None, status_filter=None, current_user=DummyUser())
    assert res["total"] == 1
    assert isinstance(res["data"], list)


@pytest.mark.asyncio
async def test_read_intents_failure(monkeypatch):
    """read_intents should raise HTTPException when store fails"""
    async def fake_list_intents(*args, **kwargs):
        raise Exception("db error")

    monkeypatch.setattr(routes.store, "list_intents", fake_list_intents)

    with pytest.raises(Exception) as exc:
        await routes.read_intents(current_user=DummyUser())
    assert "Failed to retrieve intents" in str(exc.value)


@pytest.mark.asyncio
async def test_read_intent_success(monkeypatch):
    """read_intent returns the intent when found"""
    async def fake_get_intent(id: str):
        return SimpleNamespace(id=id, name="intent")

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)

    intent = await routes.read_intent("id-1", current_user=DummyUser())
    assert getattr(intent, "id") == "id-1"


@pytest.mark.asyncio
async def test_read_intent_not_found(monkeypatch):
    """read_intent returns HTTP 404 when not found"""
    async def fake_get_intent(id: str):
        raise routes.IntentNotFoundError("not found")

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)

    with pytest.raises(Exception) as exc:
        await routes.read_intent("missing", current_user=DummyUser())
    assert "not found" in str(exc.value)


@pytest.mark.asyncio
async def test_update_intent_success(monkeypatch):
    """update_intent should validate and call edit_intent"""
    input_data = {"name": "Updated", "relatedIntents": []}
    dummy_intent = DummyIntentInput(input_data)

    async def fake_edit_intent(intent_id: str, intent_dict: dict):
        assert intent_id == "id-1"
        assert "updated_by" in intent_dict
        return SimpleNamespace(**{**intent_dict, "id": intent_id})

    monkeypatch.setattr(routes.store, "edit_intent", fake_edit_intent)
    monkeypatch.setattr(routes, "_validate_circular_references", lambda *_: asyncio.sleep(0))

    updated = await routes.update_intent("id-1", dummy_intent, current_user=DummyUser("u2"))
    assert getattr(updated, "id") == "id-1"
    assert getattr(updated, "updated_by") == "u2"


@pytest.mark.asyncio
async def test_update_intent_circular_error(monkeypatch):
    """update_intent should return 400 when circular validation fails"""
    dummy_intent = DummyIntentInput({"name": "X"})

    async def raise_circular(*args, **kwargs):
        raise routes.CircularReferenceError("bad")

    monkeypatch.setattr(routes, "_validate_circular_references", raise_circular)

    with pytest.raises(Exception) as exc:
        await routes.update_intent("id", dummy_intent, current_user=DummyUser())
    assert "Circular reference validation failed" in str(exc.value)


@pytest.mark.asyncio
async def test_update_intent_not_found(monkeypatch):
    """update_intent should return 404 when store.edit_intent raises IntentNotFoundError"""
    dummy_intent = DummyIntentInput({"name": "X"})

    async def fake_edit_intent(*args, **kwargs):
        raise routes.IntentNotFoundError("missing")

    monkeypatch.setattr(routes.store, "edit_intent", fake_edit_intent)
    monkeypatch.setattr(routes, "_validate_circular_references", lambda *_: asyncio.sleep(0))

    with pytest.raises(Exception) as exc:
        await routes.update_intent("id", dummy_intent, current_user=DummyUser())
    assert "missing" in str(exc.value)


@pytest.mark.asyncio
async def test_delete_intent_success(monkeypatch):
    """delete_intent should call store.delete_intent without error"""
    async def fake_delete_intent(intent_id: str):
        return None

    monkeypatch.setattr(routes.store, "delete_intent", fake_delete_intent)

    result = await routes.delete_intent("id-1", current_user=DummyUser())
    assert result is None


@pytest.mark.asyncio
async def test_delete_intent_not_found(monkeypatch):
    """delete_intent should return 404 when not found"""
    async def fake_delete_intent(*args, **kwargs):
        raise routes.IntentNotFoundError("nope")

    monkeypatch.setattr(routes.store, "delete_intent", fake_delete_intent)

    with pytest.raises(Exception) as exc:
        await routes.delete_intent("id-1", current_user=DummyUser())
    assert "nope" in str(exc.value)


@pytest.mark.asyncio
async def test_publish_intent_success(monkeypatch):
    """publish_intent should set status to published and call edit_intent"""
    async def fake_get_intent(id: str):
        return SimpleNamespace(id=id, status="draft")

    async def fake_edit_intent(intent_id: str, update_data: dict):
        assert update_data["status"] == "published"
        return SimpleNamespace(id=intent_id, status="published", **update_data)

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)
    monkeypatch.setattr(routes.store, "edit_intent", fake_edit_intent)

    published = await routes.publish_intent("i1", current_user=DummyUser("pubby"))
    assert getattr(published, "status") == "published"
    assert getattr(published, "published_by") == "pubby"


@pytest.mark.asyncio
async def test_publish_intent_already_published(monkeypatch):
    """If intent already published, endpoint should raise HTTP 400"""
    async def fake_get_intent(id: str):
        return SimpleNamespace(id=id, status="published")

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)

    with pytest.raises(Exception) as exc:
        await routes.publish_intent("i1", current_user=DummyUser())
    assert "Intent is already published" in str(exc.value)


@pytest.mark.asyncio
async def test_publish_intent_not_found(monkeypatch):
    """publish_intent should return 404 when intent missing"""
    async def fake_get_intent(id: str):
        raise routes.IntentNotFoundError("nope")

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)

    with pytest.raises(Exception) as exc:
        await routes.publish_intent("i1", current_user=DummyUser())
    assert "nope" in str(exc.value)


@pytest.mark.asyncio
async def test_unpublish_intent_success(monkeypatch):
    """unpublish_intent should set status to draft and call edit_intent"""
    async def fake_get_intent(id: str):
        return SimpleNamespace(id=id, status="published")

    async def fake_edit_intent(intent_id: str, update_data: dict):
        assert update_data["status"] == "draft"
        return SimpleNamespace(id=intent_id, status="draft", **update_data)

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)
    monkeypatch.setattr(routes.store, "edit_intent", fake_edit_intent)

    unpublished = await routes.unpublish_intent("i1", current_user=DummyUser("u3"))
    assert getattr(unpublished, "status") == "draft"
    assert getattr(unpublished, "unpublished_by") == "u3"


@pytest.mark.asyncio
async def test_unpublish_intent_not_published(monkeypatch):
    """unpublish should error if intent not published"""
    async def fake_get_intent(id: str):
        return SimpleNamespace(id=id, status="draft")

    monkeypatch.setattr(routes.store, "get_intent", fake_get_intent)

    with pytest.raises(Exception) as exc:
        await routes.unpublish_intent("i1", current_user=DummyUser())
    assert "Intent is not published" in str(exc.value)


@pytest.mark.asyncio
async def test_get_intent_history_success(monkeypatch):
    """get_intent_history should return stored history list"""
    async def fake_get_history(intent_id: str, limit: int):
        return [{"version": 1}, {"version": 2}]

    monkeypatch.setattr(routes.store, "get_intent_history", fake_get_history)

    history = await routes.get_intent_history("i1", limit=2, current_user=DummyUser())
    assert isinstance(history, list)
    assert history[0]["version"] == 1


@pytest.mark.asyncio
async def test_get_intent_history_not_found(monkeypatch):
    """get_intent_history should return 404 when missing"""
    async def fake_get_history(*args, **kwargs):
        raise routes.IntentNotFoundError("no history")

    monkeypatch.setattr(routes.store, "get_intent_history", fake_get_history)

    with pytest.raises(Exception) as exc:
        await routes.get_intent_history("i1", current_user=DummyUser())
    assert "no history" in str(exc.value)


@pytest.mark.asyncio
async def test_rollback_intent_version_success(monkeypatch):
    """rollback_intent_version should call store.rollback_intent and return restored intent"""
    async def fake_rollback(intent_id: str, version_number: int):
        return SimpleNamespace(id=intent_id, version=version_number)

    monkeypatch.setattr(routes.store, "rollback_intent", fake_rollback)

    restored = await routes.rollback_intent_version("i1", 2, current_user=DummyUser())
    assert getattr(restored, "version") == 2


@pytest.mark.asyncio
async def test_rollback_intent_version_errors(monkeypatch):
    """rollback should surface version or not-found errors as 404"""
    async def fake_rollback_err(*args, **kwargs):
        raise routes.IntentVersionError("bad version")

    monkeypatch.setattr(routes.store, "rollback_intent", fake_rollback_err)

    with pytest.raises(Exception) as exc:
        await routes.rollback_intent_version("i1", 99, current_user=DummyUser())
    assert "bad version" in str(exc.value)