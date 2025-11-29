import importlib
from typing import List

import pytest

from app.bot.nlu.entity_extractors import (
    CRFEntityExtractor,
    SynonymReplacer,
)
from app.bot.nlu.entity_extractors import __all__ as entity_extractors_all
from app.bot.nlu.entity_extractors.crf_entity_extractor import CRFEntityExtractor as CRFEntityExtractorSource
from app.bot.nlu.entity_extractors.synonym_replacer import SynonymReplacer as SynonymReplacerSource


@pytest.fixture(name="module_docstring")
def fixture_module_docstring() -> str:
    """Return the module docstring for the entity extractors package."""
    module = importlib.import_module("app.bot.nlu.entity_extractors")
    return module.__doc__ or ""


def test_module_docstring_explains_reexport(module_docstring: str) -> None:
    """Verify the package docstring clarifies that it re-exports extractor components."""
    assert "re-export" in module_docstring.lower()
    assert "pipeline" in module_docstring.lower()


def test_entity_extractors_all_defines_public_api() -> None:
    """Ensure __all__ explicitly lists the re-exported extractor classes."""
    expected_exports: List[str] = ["CRFEntityExtractor", "SynonymReplacer"]
    assert entity_extractors_all == expected_exports


def test_crf_entity_extractor_reexport_matches_source() -> None:
    """Verify the CRFEntityExtractor symbol points to the same class object as the source module."""
    assert CRFEntityExtractor is CRFEntityExtractorSource


def test_synonym_replacer_reexport_matches_source() -> None:
    """Verify the SynonymReplacer symbol points to the same class object as the source module."""
    assert SynonymReplacer is SynonymReplacerSource


def test_star_import_respects_all() -> None:
    """Confirm that performing a star import would only expose the declared export names."""
    module = importlib.import_module("app.bot.nlu.entity_extractors")
    exported_names = {name for name in dir(module) if not name.startswith("__")}
    assert set(entity_extractors_all).issubset(exported_names)
    assert exported_names.issuperset(entity_extractors_all)


# Additional tests for explicit failure could include ensuring no unexpected attributes are re-exported.

def test_no_additional_public_symbols() -> None:
    """Ensure no additional public symbols are introduced beyond the declared exports."""
    module = importlib.import_module("app.bot.nlu.entity_extractors")
    public_symbols = [name for name in dir(module) if not name.startswith("__")]
    assert set(public_symbols) == set(entity_extractors_all)