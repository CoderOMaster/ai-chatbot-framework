from __future__ import annotations

from bson import ObjectId
import pytest

from app.admin.entities.schemas import Entity, EntityValue


def test_entity_value_defaults_to_empty_synonyms() -> None:
    """Ensures EntityValue uses a default empty synonym list and stores the provided value."""

    entity_value = EntityValue(value="color")

    assert entity_value.value == "color"
    assert isinstance(entity_value.synonyms, list)
    assert entity_value.synonyms == []


def test_entity_value_synonyms_are_isolated_between_instances() -> None:
    """Verifies that the default synonym list is not shared between EntityValue instances."""

    entity_value_a = EntityValue(value="size")
    entity_value_b = EntityValue(value="shape")

    entity_value_a.synonyms.append("large")

    assert entity_value_a.synonyms == ["large"]
    assert entity_value_b.synonyms == []


def test_entity_defaults_entity_values_list_and_allows_append() -> None:
    """Checks that Entity defaults entity_values to an empty, isolated list that can be mutated safely."""

    entity_a = Entity(name="temperature")
    entity_b = Entity(name="pressure")

    entity_a.entity_values.append(EntityValue(value="hot"))

    assert entity_a.entity_values != entity_b.entity_values
    assert entity_b.entity_values == []


def test_entity_accepts_objectid_string_alias_and_serializes_to_string() -> None:
    """Validates that Entity accepts the Mongo-style _id alias and serializes ObjectId instances to string."""

    raw_object_id = ObjectId()
    entity = Entity(_id=str(raw_object_id), name="status")

    assert isinstance(entity.id, ObjectId)
    assert entity.id == raw_object_id

    serialized = entity.model_dump(by_alias=True)
    assert serialized["_id"] == str(raw_object_id)
    assert serialized["name"] == "status"


def test_entity_raises_on_invalid_objectid() -> None:
    """Ensures invalid ObjectId inputs raise a validation error through the shared ObjectIdField."""

    with pytest.raises(ValueError):
        Entity(_id="not_a_valid_object_id", name="invalid")


def test_entity_accepts_entity_values_as_dicts() -> None:
    """Confirms that entity_values accepts dict payloads for HTTP/JSON friendly usage."""

    payload = {"name": "color", "entity_values": [{"value": "blue", "synonyms": ["azure"]}]}
    entity = Entity(**payload)

    assert len(entity.entity_values) == 1
    first_value = entity.entity_values[0]
    assert first_value.value == "blue"
    assert first_value.synonyms == ["azure"]


def test_entity_model_config_allows_arbitrary_types() -> None:
    """Verifies that arbitrary types can be assigned and persisted because of model_config."""

    class CustomType:
        def __init__(self, payload: str) -> None:
            self.payload = payload

        def __repr__(self) -> str:  # pragma: no cover - simply for readability
            return f"CustomType({self.payload})"

    custom_instance = CustomType("extra")
    entity = Entity(name="custom", entity_values=[], id=custom_instance)

    assert entity.id is custom_instance
    assert entity.name == "custom"
    assert entity.entity_values == []