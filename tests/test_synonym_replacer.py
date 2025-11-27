import pytest
from datetime import datetime
from typing import Dict, Any

from app.bot.nlu.entity_extractors import synonym_replacer as sr


@pytest.fixture
def sample_synonyms() -> Dict[str, str]:
    return {"usa": "united states", "ny": "new york", "tx": "texas"}


@pytest.fixture
def replacer(sample_synonyms) -> sr.SynonymReplacer:
    return sr.SynonymReplacer(synonyms=sample_synonyms)


def test_metrics_to_dict_contains_fields() -> None:
    """Verify ReplacementMetrics.to_dict returns expected keys and types."""
    metrics = sr.ReplacementMetrics(total_replacements=5, replacement_hits=2)
    d = metrics.to_dict()
    assert d["total_replacements"] == 5
    assert d["replacement_hits"] == 2
    # timestamp should be ISO format string parseable to datetime
    assert isinstance(d["timestamp"], str)
    datetime.fromisoformat(d["timestamp"])  # should not raise


def test_init_with_invalid_synonyms_type_raises() -> None:
    """Constructing SynonymReplacer with non-dict synonyms should raise TypeError."""
    with pytest.raises(TypeError):
        sr.SynonymReplacer(synonyms=[("a", "b")])  # list is invalid


def test_init_with_invalid_synonym_key_value_raises() -> None:
    """Synonyms with non-string keys or values should raise ValueError."""
    # non-string key
    with pytest.raises(ValueError):
        sr.SynonymReplacer(synonyms={1: "one"})

    # non-string value
    with pytest.raises(ValueError):
        sr.SynonymReplacer(synonyms={"one": 1})


def test_update_synonyms_success_and_state_update(replacer: sr.SynonymReplacer) -> None:
    """update_synonyms should replace internal synonyms dict and log info."""
    new = {"sfo": "san francisco"}
    replacer.update_synonyms(new)
    assert replacer.synonyms == new


def test_update_synonyms_invalid_raises(replacer: sr.SynonymReplacer) -> None:
    """update_synonyms should validate input and raise on invalid types."""
    with pytest.raises(TypeError):
        replacer.update_synonyms("not a dict")

    with pytest.raises(ValueError):
        replacer.update_synonyms({"good": 123})


def test_replace_synonyms_non_dict_entities_raises(replacer: sr.SynonymReplacer) -> None:
    """replace_synonyms should enforce entities being a dict."""
    with pytest.raises(TypeError):
        replacer.replace_synonyms([("loc", "NY")])  # list is invalid


def test_replace_synonyms_replaces_case_insensitive_and_metrics(replacer: sr.SynonymReplacer) -> None:
    """Replacement should be case-insensitive and metrics must update correctly."""
    entities = {"location": "NY", "country": "USA", "state": "tx", "other": "unchanged"}
    before_metrics = replacer.get_metrics()
    result = replacer.replace_synonyms(entities)

    # Check replacements (keys in synonyms are lowercase)
    assert result["location"] == "new york"
    assert result["country"] == "united states"
    assert result["state"] == "texas"
    assert result["other"] == "unchanged"

    metrics = replacer.get_metrics()
    # total_replacements should increase by number of entities
    assert metrics["total_replacements"] >= len(entities)
    # replacement_hits should be 3
    assert metrics["replacement_hits"] >= 3


def test_reset_metrics(replacer: sr.SynonymReplacer) -> None:
    """reset_metrics should reset metrics to zeroed ReplacementMetrics."""
    replacer.replace_synonyms({"a": "usa"})
    assert replacer.get_metrics()["total_replacements"] > 0
    replacer.reset_metrics()
    assert replacer.get_metrics()["total_replacements"] == 0
    assert replacer.get_metrics()["replacement_hits"] == 0


# Tests for lambda_handler

def test_lambda_handler_replace_missing_entities_returns_400() -> None:
    """If operation is replace but entities missing, lambda should return 400."""
    event = {"operation": "replace", "synonyms": {}}
    resp = sr.lambda_handler(event, context=None)
    assert resp["statusCode"] == 400
    assert "Missing 'entities'" in resp["body"]["error"]


def test_lambda_handler_replace_success_returns_200_and_metrics() -> None:
    """Lambda replace operation should return replaced entities and metrics on success."""
    event = {
        "operation": "replace",
        "synonyms": {"paris": "paris_fr"},
        "entities": {"city": "Paris", "country": "France"},
    }
    resp = sr.lambda_handler(event, context=None)
    assert resp["statusCode"] == 200
    body = resp["body"]
    assert body["entities"]["city"] == "paris_fr"
    assert "metrics" in body
    assert isinstance(body["metrics"], dict)


def test_lambda_handler_replace_with_invalid_entities_returns_400() -> None:
    """If entities is of wrong type, lambda should catch TypeError and return 400."""
    event = {"operation": "replace", "synonyms": {"a": "b"}, "entities": [1, 2, 3]}
    resp = sr.lambda_handler(event, context=None)
    assert resp["statusCode"] == 400
    assert "Entities must be a dictionary" in resp["body"]["error"]


def test_lambda_handler_update_missing_synonyms_returns_400() -> None:
    """If operation is update but synonyms missing, lambda should return 400."""
    event = {"operation": "update"}
    resp = sr.lambda_handler(event, context=None)
    assert resp["statusCode"] == 400
    assert "Missing 'synonyms'" in resp["body"]["error"]


def test_lambda_handler_update_success_returns_200() -> None:
    """Lambda update operation should update synonyms and return count."""
    event = {"operation": "update", "synonyms": {"la": "los angeles", "sf": "san francisco"}}
    resp = sr.lambda_handler(event, context=None)
    assert resp["statusCode"] == 200
    assert resp["body"]["count"] == 2


def test_lambda_handler_unknown_operation_returns_400() -> None:
    """Unsupported operation should result in 400 and helpful error."""
    event = {"operation": "delete"}
    resp = sr.lambda_handler(event, context=None)
    assert resp["statusCode"] == 400
    assert "Unknown operation" in resp["body"]["error"]


def test_lambda_handler_internal_exception_returns_500(monkeypatch) -> None:
    """Simulate unexpected exception inside handler to ensure 500 is returned."""
    # Monkeypatch SynonymReplacer.replace_synonyms to raise a generic exception
    def _boom(self, entities: Dict[str, Any]):
        raise RuntimeError("boom")

    monkeypatch.setattr(sr.SynonymReplacer, "replace_synonyms", _boom)

    event = {"operation": "replace", "synonyms": {}, "entities": {"x": "y"}}
    resp = sr.lambda_handler(event, context=None)
    assert resp["statusCode"] == 500
    assert "Internal server error" in resp["body"]["error"]