"""Entity extraction components for NLU pipeline.

This package provides entity extraction capabilities including CRF-based
Named Entity Recognition and synonym replacement for entity normalization.
"""

from .crf_entity_extractor import CRFEntityExtractor
from .synonym_replacer import SynonymReplacer

__all__ = ["CRFEntityExtractor", "SynonymReplacer"]