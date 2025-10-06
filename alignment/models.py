"""Immutable data models for the semantic alignment engine.

These models define the vocabulary for keyed list alignment: rules that
declare how list elements should be matched by identity, keys extracted
from those elements, match pairs, complete alignment results, and
machine-readable diagnostics.

All models are frozen dataclasses with ``slots=True``, following the
project convention for immutable value objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AlignmentRule:
    """Declares how list elements at a JSON path should be matched by identity.

    ``path`` uses normalized JSONPath-subset notation (e.g., ``$.users``).
    ``fields`` names one or more dict keys whose combined value forms the
    identity of each list element.

    A single-field rule uses a 1-tuple: ``fields=("id",)``.
    A composite rule uses an N-tuple: ``fields=("region", "number")``.
    Field ordering is significant for key construction and diagnostics.
    """

    path: str
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("AlignmentRule requires a non-empty path")
        if not self.fields:
            raise ValueError("AlignmentRule requires at least one field")
        seen: set[str] = set()
        for field in self.fields:
            if not isinstance(field, str) or not field.strip():
                raise ValueError(
                    f"AlignmentRule field must be a non-empty string, got: {field!r}"
                )
            if field in seen:
                raise ValueError(f"Duplicate field in AlignmentRule: {field!r}")
            seen.add(field)


@dataclass(frozen=True, slots=True)
class AlignmentKey:
    """Identity extracted from one list element using an AlignmentRule.

    ``values`` contains the element's field values in the order declared
    by the rule's ``fields`` tuple.  For a rule with
    ``fields=("region", "number")``, an element ``{"region": "US", "number": 42}``
    produces ``values=("US", 42)``.

    AlignmentKey is hashable by design -- it is used as a dict key to
    build the expected-to-actual element mapping during alignment execution.
    """

    values: tuple[Any, ...]

    def __post_init__(self) -> None:
        try:
            hash(self.values)
        except TypeError as exc:
            raise TypeError(
                f"AlignmentKey values must be hashable, got: {self.values!r}"
            ) from exc


@dataclass(frozen=True, slots=True)
class AlignmentMatch:
    """Pairs one expected-list element with one actual-list element by key.

    ``key`` is the common identity.  ``expected_index`` and ``actual_index``
    are positional indices in their respective lists.  The diff engine uses
    these pairs to recurse into matched elements rather than treating
    them as unrelated add/remove pairs.
    """

    key: AlignmentKey
    expected_index: int
    actual_index: int


@dataclass(frozen=True, slots=True)
class AlignmentFinding:
    """Machine-readable diagnostic emitted during alignment execution.

    Modelled after ``PolicyFinding`` for consistent handling in review
    reports and CI output.  The ``code`` field uses a fixed vocabulary
    defined by the ambiguity model.
    """

    code: str
    message: str
    severity: str = "warning"
    path: str | None = None
    element_index: int | None = None
    list_side: str | None = None


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """Complete alignment outcome for one list-path comparison.

    This is the primary data structure consumed by the diff engine.
    It partitions every element from both lists into exactly one of
    three categories: matched (same key in both), unmatched expected
    (key only in expected), or unmatched actual (key only in actual).

    ``rule`` records which AlignmentRule produced this result.
    ``findings`` carries any ambiguity warnings discovered during alignment.
    """

    rule: AlignmentRule
    matches: tuple[AlignmentMatch, ...]
    unmatched_expected: tuple[int, ...]
    unmatched_actual: tuple[int, ...]
    findings: tuple[AlignmentFinding, ...]
