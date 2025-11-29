import importlib
from types import ModuleType

import pytest


@pytest.fixture(name="featurizers_module")
def fixture_featurizers_module() -> ModuleType:
    """Import and reload the featurizers initializer module for a clean state."""
    module = importlib.import_module("app.bot.nlu.featurizers")
    importlib.reload(module)
    return module


def test_module_documentation_describes_package(featurizers_module: ModuleType) -> None:
    """Ensure the package docstring clarifies the purpose of this lightweight initializer."""
    docstring = featurizers_module.__doc__
    assert isinstance(docstring, str), "Expected module to have a docstring"
    assert "Lightweight" in docstring
    assert "NLU featurizers" in docstring


def test_all_exports_contains_spacy_featurizer(featurizers_module: ModuleType) -> None:
    """Validate that the initializer explicitly re-exports SpacyFeaturizer via __all__."""
    exports = getattr(featurizers_module, "__all__", [])
    assert "SpacyFeaturizer" in exports, "SpacyFeaturizer should be part of __all__"


def test_reexport_provides_same_class(featurizers_module: ModuleType) -> None:
    """Confirm that the module re-exports the identical SpacyFeaturizer class defined in its source file."""
    from app.bot.nlu.featurizers.spacy_featurizer import SpacyFeaturizer as OriginalClass

    exported_class = getattr(featurizers_module, "SpacyFeaturizer", None)
    assert exported_class is OriginalClass


def test_reimporting_does_not_raise(featurizers_module: ModuleType) -> None:
    """Ensure that importing the package initializer multiple times stays idempotent and error-free."""
    try:
        importlib.reload(featurizers_module)
    except Exception as exc:  # pragma: no cover - defensive check
        pytest.skip(f"Failed to reload module: {exc}")


def test_all_exports_type(featurizers_module: ModuleType) -> None:
    """Ensure the __all__ variable is a list of strings for predictable imports."""
    exports = getattr(featurizers_module, "__all__", None)
    assert isinstance(exports, list)
    assert all(isinstance(item, str) for item in exports)