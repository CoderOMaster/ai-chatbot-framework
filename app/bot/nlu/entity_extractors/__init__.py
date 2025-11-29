"""Re-export entity extractor components for pipeline consumers."""

from .crf_entity_extractor import CRFEntityExtractor
from .synonym_replacer import SynonymReplacer

__all__ = ["CRFEntityExtractor", "SynonymReplacer"]

# Clean up the namespace to avoid exposing submodule names
del crf_entity_extractor
del synonym_replacer