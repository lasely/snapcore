"""Alignment executor -- matches list elements by identity keys.

Given two lists (expected and actual) and an ``AlignmentRule`` declaring
which dict fields form the identity key, ``align_lists`` partitions every
element index into one of three buckets:

* **matched** -- same key appears exactly once in both lists
* **unmatched_expected** -- key appears in expected but not actual (or is
  ambiguous due to duplicates / extraction failure)
* **unmatched_actual** -- key appears in actual but not expected (same
  caveats)

The executor is a pure function: it reads the two lists and the rule,
returns an ``AlignmentResult``, and never mutates its inputs.

Complexity
----------
Key extraction is O(n + m) where n = len(expected), m = len(actual).
Index-mapping construction is O(n + m).  Matching is O(min(n, m)).
Total: **O(n + m)** time and space -- acceptable for lists of 1000+
elements and a strict improvement over the O(n * m) LCS fallback.
"""

from __future__ import annotations

from typing import Any

from .findings import (
    build_element_type_finding,
    build_key_duplicate_finding,
    build_key_missing_finding,
    build_key_unhashable_finding,
    build_partial_alignment_finding,
)
from .models import (
    AlignmentFinding,
    AlignmentKey,
    AlignmentMatch,
    AlignmentResult,
    AlignmentRule,
)


class _Missing:
    """Sentinel for a key field that is absent from a dict element.

    We cannot use ``None`` as the sentinel because ``None`` is a valid
    JSON value (``null``) that a user might legitimately use as a key
    field value.  ``_MISSING`` is a module-level singleton that is never
    equal to any JSON value and is always hashable.
    """

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<MISSING>"

    def __hash__(self) -> int:
        return hash(("_Missing_sentinel",))

    def __eq__(self, other: object) -> bool:
        return self is other


_MISSING = _Missing()


def align_lists(
    expected: list[Any],
    actual: list[Any],
    rule: AlignmentRule,
    path: str,
) -> AlignmentResult:
    """Match elements of *expected* and *actual* by identity key.

    Parameters
    ----------
    expected:
        The expected list (from the stored snapshot).
    actual:
        The actual list (from the test value).
    rule:
        The ``AlignmentRule`` declaring which dict fields form the key.
    path:
        The JSONPath of this list (e.g., ``"$.users"``), used in findings.

    Returns
    -------
    AlignmentResult
        Partitioned indices plus any diagnostic findings.

    Algorithm
    ---------
    1. Extract keys from every element in both lists, collecting findings
       for non-dict elements, missing fields, and unhashable values.
    2. Build ``key -> list[index]`` mappings for each side.
    3. Detect duplicate keys within a single side: move ALL indices with
       that key into the unmatched pool and emit a finding.
    4. Intersect the two unique-key sets to produce matched pairs.
    5. Remaining unique keys become unmatched_expected / unmatched_actual.
    6. If the result is a partial alignment (some matched, some not),
       emit an informational finding.
    """
    findings: list[AlignmentFinding] = []

    expected_keys = _extract_keys(expected, rule, path, "expected", findings)
    actual_keys = _extract_keys(actual, rule, path, "actual", findings)

    expected_map: dict[AlignmentKey, list[int]] = {}
    for idx, key in expected_keys.items():
        expected_map.setdefault(key, []).append(idx)

    actual_map: dict[AlignmentKey, list[int]] = {}
    for idx, key in actual_keys.items():
        actual_map.setdefault(key, []).append(idx)

    expected_unmatched_from_dup: set[int] = set()
    actual_unmatched_from_dup: set[int] = set()

    for key, indices in list(expected_map.items()):
        if len(indices) > 1:
            findings.append(
                build_key_duplicate_finding(
                    path=path,
                    key_value=key.values,
                    indices=tuple(indices),
                    list_side="expected",
                )
            )
            expected_unmatched_from_dup.update(indices)
            del expected_map[key]

    for key, indices in list(actual_map.items()):
        if len(indices) > 1:
            findings.append(
                build_key_duplicate_finding(
                    path=path,
                    key_value=key.values,
                    indices=tuple(indices),
                    list_side="actual",
                )
            )
            actual_unmatched_from_dup.update(indices)
            del actual_map[key]

    common_keys = set(expected_map.keys()) & set(actual_map.keys())
    matches: list[AlignmentMatch] = []
    for key in sorted(common_keys, key=lambda k: expected_map[k][0]):
        matches.append(
            AlignmentMatch(
                key=key,
                expected_index=expected_map[key][0],
                actual_index=actual_map[key][0],
            )
        )

    matched_expected_indices = {m.expected_index for m in matches}
    matched_actual_indices = {m.actual_index for m in matches}

    all_expected_indices = set(range(len(expected)))
    all_actual_indices = set(range(len(actual)))

    unmatched_expected = sorted(all_expected_indices - matched_expected_indices)
    unmatched_actual = sorted(all_actual_indices - matched_actual_indices)

    if matches and (unmatched_expected or unmatched_actual):
        findings.append(
            build_partial_alignment_finding(
                path=path,
                matched=len(matches),
                unmatched_expected=len(unmatched_expected),
                unmatched_actual=len(unmatched_actual),
            )
        )

    return AlignmentResult(
        rule=rule,
        matches=tuple(matches),
        unmatched_expected=tuple(unmatched_expected),
        unmatched_actual=tuple(unmatched_actual),
        findings=tuple(findings),
    )


def _extract_keys(
    elements: list[Any],
    rule: AlignmentRule,
    path: str,
    list_side: str,
    findings: list[AlignmentFinding],
) -> dict[int, AlignmentKey]:
    """Extract alignment keys from every element, returning index->key mapping.

    Elements that cannot produce a valid hashable key are excluded from
    the returned mapping and the appropriate finding is appended.
    """
    keys: dict[int, AlignmentKey] = {}

    for idx, element in enumerate(elements):
        if not isinstance(element, dict):
            findings.append(
                build_element_type_finding(
                    path=path,
                    element_index=idx,
                    actual_type=type(element).__name__,
                    list_side=list_side,
                )
            )
            continue

        field_values: list[Any] = []
        extraction_failed = False

        for field in rule.fields:
            if field not in element:
                findings.append(
                    build_key_missing_finding(
                        path=path,
                        element_index=idx,
                        field=field,
                        list_side=list_side,
                    )
                )
                field_values.append(_MISSING)
            else:
                value = element[field]
                try:
                    hash(value)
                except TypeError:
                    findings.append(
                        build_key_unhashable_finding(
                            path=path,
                            element_index=idx,
                            field=field,
                            value_type=type(value).__name__,
                            list_side=list_side,
                        )
                    )
                    extraction_failed = True
                    break
                field_values.append(value)

        if extraction_failed:
            continue

        if any(v is _MISSING for v in field_values):
            continue

        wrapped = tuple(_wrap_for_type_safety(v) for v in field_values)
        keys[idx] = AlignmentKey(values=wrapped)

    return keys


def _wrap_for_type_safety(value: Any) -> Any:
    """Wrap values to ensure type-strict hashing and equality.

    Python's built-in hash makes ``hash(1) == hash(True)`` and
    ``1 == True``, which would incorrectly match an element with
    ``id=1`` against one with ``id=True``.  We wrap booleans in a
    tagged tuple to break that equivalence.

    The sentinel ``_MISSING`` passes through unwrapped since it already
    has unique hash/equality semantics.
    """
    if value is _MISSING:
        return value
    if isinstance(value, bool):
        return ("__bool__", value)
    return value
