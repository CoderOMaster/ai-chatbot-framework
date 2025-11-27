import pytest
from pydantic import ValidationError

from app.admin.entities.schemas import (
    EntityValue,
    Entity,
    EntityCreate,
    EntityUpdate,
)


def test_entity_value_success() -> None:
    """Valid EntityValue is accepted and whitespace is trimmed for value and synonyms."""
    ev = EntityValue(value="  hello world  ", synonyms=[" one ", "two"])
    assert ev.value == "hello world"
    assert ev.synonyms == ["one", "two"]


def test_entity_value_empty_value_raises() -> None:
    """A value that is only whitespace should raise a ValidationError with the custom message."""
    with pytest.raises(ValidationError) as excinfo:
        EntityValue(value="   ", synonyms=[])
    assert "Value cannot be empty or whitespace only" in str(excinfo.value)


def test_entity_value_value_too_long_raises() -> None:
    """A value longer than 500 characters should raise a ValidationError."""
    long_value = "x" * 501
    with pytest.raises(ValidationError):
        EntityValue(value=long_value, synonyms=[])


def test_synonym_empty_raises() -> None:
    """Individual synonym entries that are empty or whitespace only should raise an error."""
    with pytest.raises(ValidationError) as excinfo:
        EntityValue(value="ok", synonyms=["", "valid"])
    assert "Synonyms cannot be empty or whitespace only" in str(excinfo.value)


def test_synonym_item_too_long_raises() -> None:
    """A single synonym longer than 500 characters should raise a ValidationError."""
    long_syn = "s" * 501
    with pytest.raises(ValidationError) as excinfo:
        EntityValue(value="ok", synonyms=[long_syn])
    assert "Each synonym must not exceed 500 characters" in str(excinfo.value)


def test_synonyms_list_too_many_items_raises() -> None:
    """More than 50 synonyms in the list should violate the Field(max_length=50) constraint."""
    many = [f"s{i}" for i in range(51)]
    with pytest.raises(ValidationError):
        EntityValue(value="ok", synonyms=many)


def test_entity_name_valid_and_trimmed() -> None:
    """Entity and EntityCreate accept valid names and trim surrounding whitespace."""
    name = "  My-Entity_1 Name  "
    e = Entity(name=name, entity_values=[])
    assert e.name == "My-Entity_1 Name"

    ec = EntityCreate(name=name)
    assert ec.name == "My-Entity_1 Name"


def test_entity_name_invalid_chars_raises() -> None:
    """Names with disallowed special characters should raise ValidationError."""
    bad_name = "Invalid@Name!"
    with pytest.raises(ValidationError) as excinfo1:
        Entity(name=bad_name, entity_values=[])
    assert "Name can only contain alphanumeric characters" in str(excinfo1.value)

    with pytest.raises(ValidationError) as excinfo2:
        EntityCreate(name=bad_name)
    assert "Name can only contain alphanumeric characters" in str(excinfo2.value)


def test_entity_name_empty_whitespace_raises() -> None:
    """Names that are only whitespace should raise a ValidationError."""
    with pytest.raises(ValidationError) as excinfo:
        Entity(name="   ", entity_values=[])
    assert "Name cannot be empty or whitespace only" in str(excinfo.value)


def test_entity_name_too_long_raises() -> None:
    """Names longer than 255 characters should raise a ValidationError."""
    long_name = "n" * 256
    with pytest.raises(ValidationError):
        Entity(name=long_name, entity_values=[])


def test_entity_update_name_none_allowed() -> None:
    """EntityUpdate should allow name to be omitted or explicitly set to None."""
    eu1 = EntityUpdate()
    assert eu1.name is None

    eu2 = EntityUpdate(name=None)
    assert eu2.name is None


def test_entity_update_name_invalid_chars_raises() -> None:
    """Invalid names in EntityUpdate should raise ValidationError (unless None)."""
    with pytest.raises(ValidationError):
        EntityUpdate(name="Bad&Name")


def test_entity_values_default_empty_list() -> None:
    """EntityCreate should default entity_values to an empty list when not provided."""
    ec = EntityCreate(name="TestName")
    assert isinstance(ec.entity_values, list)
    assert ec.entity_values == []


def test_entity_with_values_success() -> None:
    """Entity can be constructed with nested EntityValue entries and preserves them."""
    ev = EntityValue(value="v1", synonyms=["s1"])
    e = Entity(name="ValidName", entity_values=[ev])
    assert len(e.entity_values) == 1
    assert e.entity_values[0].value == "v1"