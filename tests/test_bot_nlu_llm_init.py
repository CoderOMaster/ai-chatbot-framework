"""Tests for the LLM NLU package entry point."""

from types import ModuleType

import pytest

from app.bot.nlu import llm
from app.bot.nlu.llm.zero_shot_nlu_openai import ZeroShotNLUOpenAI


@pytest.fixture

def llm_module() -> ModuleType:
    """Fixture providing the llm package module."""
    return llm


def test_llm_module_docstring_describes_scope(llm_module: ModuleType) -> None:
    """The package docstring should explain it provides optional LLM-based NLU components."""
    assert llm_module.__doc__ is not None
    assert "optional LLM-based NLU components" in llm_module.__doc__


def test_zero_shot_nlu_openai_is_reexported(llm_module: ModuleType) -> None:
    """The ZeroShotNLUOpenAI class must be available on the llm package namespace."""
    assert hasattr(llm_module, "ZeroShotNLUOpenAI"), "ZeroShotNLUOpenAI should be re-exported"
    assert llm_module.ZeroShotNLUOpenAI is ZeroShotNLUOpenAI


def test___all___contains_only_zero_shot_nlu_openai(llm_module: ModuleType) -> None:
    """The public API should only expose ZeroShotNLUOpenAI via __all__."""
    assert isinstance(llm_module.__all__, list)
    assert llm_module.__all__ == ["ZeroShotNLUOpenAI"]


def test_importing_from_package_returns_same_class() -> None:
    """Importing ZeroShotNLUOpenAI through the package should resolve to the same object."""
    from app.bot.nlu.llm import ZeroShotNLUOpenAI as ReexportedZeroShot

    assert ReexportedZeroShot is ZeroShotNLUOpenAI


def test_module_has_no_extra_public_members() -> None:
    """Ensure that only the documented symbols are exported from the package."""
    allowed = set(llm.__all__)
    public_attrs = {name for name in dir(llm) if not name.startswith("_")}
    extras = public_attrs - {"__doc__", "__package__", "__loader__", "__spec__"}
    assert extras <= allowed