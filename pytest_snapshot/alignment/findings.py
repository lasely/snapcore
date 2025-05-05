"""Builder functions for alignment-specific findings.

Centralizes finding construction so ambiguity codes and message templates
are not duplicated across the alignment engine and reporting layers.
Follows the same pattern as ``policy.py`` for PolicyFinding builders.
"""

from __future__ import annotations

from typing import Any

from .models import AlignmentFinding

# -- Ambiguity codes -------------------------------------------------------
#
# ALIGNMENT_KEY_MISSING       An element lacks one or more declared key fields.
# ALIGNMENT_KEY_DUPLICATE     Two+ elements in the same list share a key value.
# ALIGNMENT_KEY_UNHASHABLE    A key field value is not hashable (dict, list).
# ALIGNMENT_ELEMENT_TYPE      A list element is not a dict; key extraction fails.
# ALIGNMENT_PATH_TYPE         The value at the registered path is not a list.
# ALIGNMENT_PARTIAL           Some elements matched, others did not (informational).

ALIGNMENT_KEY_MISSING = "alignment_key_missing"
ALIGNMENT_KEY_DUPLICATE = "alignment_key_duplicate"
ALIGNMENT_KEY_UNHASHABLE = "alignment_key_unhashable"
ALIGNMENT_ELEMENT_TYPE = "alignment_element_type"
ALIGNMENT_PATH_TYPE = "alignment_path_type"
ALIGNMENT_PARTIAL = "alignment_partial"


def build_key_missing_finding(
    *,
    path: str,
    element_index: int,
    field: str,
    list_side: str,
) -> AlignmentFinding:
    """Element is a dict but lacks a declared key field."""
    return AlignmentFinding(
        code=ALIGNMENT_KEY_MISSING,
        message=(
            f"Element at {path}[{element_index}] in {list_side} list "
            f"is missing key field '{field}'"
        ),
        severity="warning",
        path=path,
        element_index=element_index,
        list_side=list_side,
    )


def build_key_duplicate_finding(
    *,
    path: str,
    key_value: Any,
    indices: tuple[int, ...],
    list_side: str,
) -> AlignmentFinding:
    """Two or more elements in the same list share an alignment key."""
    return AlignmentFinding(
        code=ALIGNMENT_KEY_DUPLICATE,
        message=(
            f"Duplicate alignment key {key_value!r} at {path} "
            f"indices {indices} in {list_side} list"
        ),
        severity="warning",
        path=path,
        element_index=indices[0] if indices else None,
        list_side=list_side,
    )


def build_key_unhashable_finding(
    *,
    path: str,
    element_index: int,
    field: str,
    value_type: str,
    list_side: str,
) -> AlignmentFinding:
    """A key field value is not hashable (e.g., dict or list)."""
    return AlignmentFinding(
        code=ALIGNMENT_KEY_UNHASHABLE,
        message=(
            f"Unhashable key field value at {path}[{element_index}].{field}: "
            f"type {value_type}"
        ),
        severity="warning",
        path=path,
        element_index=element_index,
        list_side=list_side,
    )


def build_element_type_finding(
    *,
    path: str,
    element_index: int,
    actual_type: str,
    list_side: str,
) -> AlignmentFinding:
    """A list element is not a dict; key extraction is impossible."""
    return AlignmentFinding(
        code=ALIGNMENT_ELEMENT_TYPE,
        message=(
            f"Expected dict at {path}[{element_index}] in {list_side} list, "
            f"found {actual_type}"
        ),
        severity="warning",
        path=path,
        element_index=element_index,
        list_side=list_side,
    )


def build_path_type_finding(
    *,
    path: str,
    actual_type: str,
    list_side: str,
) -> AlignmentFinding:
    """The value at the registered path is not a list."""
    return AlignmentFinding(
        code=ALIGNMENT_PATH_TYPE,
        message=(
            f"Expected list at {path} in {list_side}, found {actual_type}"
        ),
        severity="warning",
        path=path,
        list_side=list_side,
    )


def build_partial_alignment_finding(
    *,
    path: str,
    matched: int,
    unmatched_expected: int,
    unmatched_actual: int,
) -> AlignmentFinding:
    """Some elements matched by key, others did not."""
    return AlignmentFinding(
        code=ALIGNMENT_PARTIAL,
        message=(
            f"Partial alignment at {path}: {matched} matched, "
            f"{unmatched_expected} unmatched expected, "
            f"{unmatched_actual} unmatched actual"
        ),
        severity="info",
        path=path,
    )
