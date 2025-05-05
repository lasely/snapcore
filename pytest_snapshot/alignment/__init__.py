"""Semantic alignment engine for keyed list matching.

This package provides the data model, registry, and executor for matching
list elements by identity keys rather than positional index.
"""

from .executor import align_lists
from .models import (
    AlignmentFinding,
    AlignmentKey,
    AlignmentMatch,
    AlignmentResult,
    AlignmentRule,
)
from .paths import generalize_indices, normalize_path
from .registry import AlignmentRegistry

__all__ = [
    "align_lists",
    "AlignmentFinding",
    "AlignmentKey",
    "AlignmentMatch",
    "AlignmentResult",
    "AlignmentRule",
    "AlignmentRegistry",
    "generalize_indices",
    "normalize_path",
]
