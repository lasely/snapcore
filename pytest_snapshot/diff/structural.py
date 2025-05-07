"""Structured diff rendering for JSON-compatible snapshot content.

The renderer prefers semantic change descriptions for dictionaries and lists
while retaining a unified text diff as a fallback or detailed appendix.

When an ``AlignmentRegistry`` is active, list nodes whose path matches a
registered rule are aligned by identity key (via ``align_lists``) instead
of falling through to LCS or index-based comparison.  Matched pairs are
recursed into; unmatched elements are reported as additions / removals
annotated with the entity's key values for clear diagnostics.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from ..alignment.executor import align_lists
from ..alignment.paths import generalize_brackets, generalize_indices, normalize_path
from ..models import DiffRenderResult
from .changes import Change, KeyAdded, KeyRemoved, TypeChanged, ValueChanged
from .lcs import compute_lcs_indices
from .text import TextDiffRenderer

if TYPE_CHECKING:
    from ..alignment.models import AlignmentResult
    from ..alignment.registry import AlignmentRegistry

_LCS_LIST_THRESHOLD = 50


def _unwrap_display_value(value: Any) -> Any:
    """Unwrap type-safety wrappers used in AlignmentKey values for display.

    The executor wraps booleans as ``("__bool__", True/False)`` to prevent
    hash collisions with integers.  This function strips that wrapper so
    labels render as ``flag=True`` rather than ``flag=('__bool__', True)``.
    """
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "__bool__":
        return value[1]
    return value


class StructuralDiffRenderer:
    """Render semantic JSON diffs and fall back to text when required."""

    def __init__(
        self,
        *,
        text_fallback: TextDiffRenderer | None = None,
        value_truncate_length: int = 80,
    ) -> None:
        self._text_fallback = text_fallback or TextDiffRenderer()
        self._value_truncate_length = value_truncate_length
        self._alignment_registry: AlignmentRegistry | None = None

    def render(self, expected: str, actual: str) -> str:
        """Return the formatted structural diff text for two serialized values."""
        return self.render_with_metadata(expected, actual).text

    def render_with_metadata(
        self,
        expected: str,
        actual: str,
        *,
        alignment_registry: AlignmentRegistry | None = None,
    ) -> DiffRenderResult:
        """Return structural diff text together with fallback metadata."""
        self._alignment_registry = alignment_registry
        try:
            return self._render_with_metadata_impl(expected, actual)
        finally:
            self._alignment_registry = None

    def _render_with_metadata_impl(self, expected: str, actual: str) -> DiffRenderResult:
        """Core render logic with alignment_registry available on self."""
        if expected == actual:
            return DiffRenderResult(text="", mode="structural")

        try:
            expected_obj = json.loads(expected)
            actual_obj = json.loads(actual)
        except (json.JSONDecodeError, TypeError):
            fallback = self._text_fallback.render_with_metadata(expected, actual)
            return DiffRenderResult(
                text=fallback.text,
                mode=fallback.mode,
                fallback_reason="non_json_input",
            )

        changes = self._compute_changes(expected_obj, actual_obj, path="$")
        if not changes:
            fallback = self._text_fallback.render_with_metadata(expected, actual)
            return DiffRenderResult(
                text=fallback.text,
                mode=fallback.mode,
                fallback_reason="structural_equivalence",
            )

        structural_output = self._format_changes(changes)
        text_diff = self._text_fallback.render(expected, actual)
        return DiffRenderResult(
            text=f"{structural_output}\n\nFull diff:\n{text_diff}",
            mode="structural",
        )

    def _compute_changes(
        self,
        expected: Any,
        actual: Any,
        path: str,
    ) -> list[Change]:
        if type(expected) is not type(actual):
            return [TypeChanged(path, expected, actual)]

        if isinstance(expected, dict):
            return self._diff_dicts(expected, actual, path)

        if isinstance(expected, list):
            return self._diff_lists(expected, actual, path)

        if expected != actual:
            return [ValueChanged(path, expected, actual)]

        return []

    def _diff_dicts(
        self,
        expected: dict[str, Any],
        actual: dict[str, Any],
        path: str,
    ) -> list[Change]:
        changes: list[Change] = []
        all_keys = sorted(set(expected.keys()) | set(actual.keys()))

        for key in all_keys:
            child_path = f"{path}.{key}"
            if key not in expected:
                changes.append(KeyAdded(child_path, actual[key]))
            elif key not in actual:
                changes.append(KeyRemoved(child_path, expected[key]))
            else:
                changes.extend(self._compute_changes(expected[key], actual[key], child_path))

        return changes

    def _diff_lists(
        self,
        expected: list[Any],
        actual: list[Any],
        path: str,
    ) -> list[Change]:
        # Check whether an alignment rule applies to this list path.
        # The runtime path uses concrete indices (e.g., ``$.regions[3].orders``)
        # but rules are registered with wildcards (``$.regions[*].orders``),
        # so we generalize before lookup.
        if self._alignment_registry is not None:
            normalized = normalize_path(path)
            rule = self._alignment_registry.lookup(normalized)
            if rule is None:
                # The runtime path may use concrete indices
                # (e.g., ``$.regions[3].orders``) while the rule is
                # registered with wildcards (``$.regions[*].orders``).
                generalized = generalize_indices(normalized)
                rule = self._alignment_registry.lookup(generalized)
            if rule is None:
                # The runtime path may contain entity-label brackets
                # from a parent aligned list (e.g.,
                # ``$.regions[name="US"].orders``).  Generalize ALL
                # bracket expressions to wildcards.
                generalized = generalize_brackets(normalized)
                rule = self._alignment_registry.lookup(generalized)
            if rule is not None:
                result = align_lists(expected, actual, rule, normalized)
                return self._diff_lists_aligned(expected, actual, path, result)

        if len(expected) <= _LCS_LIST_THRESHOLD and len(actual) <= _LCS_LIST_THRESHOLD:
            return self._diff_lists_lcs(expected, actual, path)
        return self._diff_lists_index(expected, actual, path)

    def _diff_lists_aligned(
        self,
        expected: list[Any],
        actual: list[Any],
        path: str,
        result: AlignmentResult,
    ) -> list[Change]:
        """Produce changes using alignment result from ``align_lists``.

        Matched pairs are recursed into with ``_compute_changes`` so that
        their internal differences are reported at full path depth.
        Unmatched elements are emitted as removals / additions with an
        entity-label path suffix (e.g., ``$.users[id=42]``) so the user
        can identify *which* entity was added or removed regardless of
        its positional index.
        """
        changes: list[Change] = []

        for match in result.matches:
            key_label = self._format_key_label(result.rule.fields, match.key.values)
            child_path = f"{path}[{key_label}]"
            changes.extend(
                self._compute_changes(
                    expected[match.expected_index],
                    actual[match.actual_index],
                    child_path,
                )
            )

        for idx in result.unmatched_expected:
            element = expected[idx]
            label = self._element_label(element, result.rule.fields, idx)
            changes.append(KeyRemoved(f"{path}[{label}]", element))

        for idx in result.unmatched_actual:
            element = actual[idx]
            label = self._element_label(element, result.rule.fields, idx)
            changes.append(KeyAdded(f"{path}[{label}]", element))

        return changes

    @staticmethod
    def _format_key_label(fields: tuple[str, ...], values: tuple[Any, ...]) -> str:
        """Build a human-readable entity label from key fields and values.

        Single-field keys produce ``id=42``.
        Composite keys produce ``region="US",number=7``.

        The ``values`` tuple may contain type-safety wrappers (tagged tuples
        for booleans) which we unwrap for display.
        """
        parts: list[str] = []
        for field, value in zip(fields, values):
            display_value = _unwrap_display_value(value)
            if isinstance(display_value, str):
                parts.append(f'{field}="{display_value}"')
            else:
                parts.append(f"{field}={display_value!r}")
        return ",".join(parts)

    @staticmethod
    def _element_label(
        element: Any,
        fields: tuple[str, ...],
        fallback_index: int,
    ) -> str:
        """Build the best available label for an unmatched element.

        If the element is a dict with the key fields present, produce the
        entity label.  Otherwise, fall back to the positional index.
        """
        if isinstance(element, dict):
            parts: list[str] = []
            for field in fields:
                if field in element:
                    value = element[field]
                    if isinstance(value, str):
                        parts.append(f'{field}="{value}"')
                    else:
                        parts.append(f"{field}={value!r}")
                else:
                    return str(fallback_index)
            return ",".join(parts)
        return str(fallback_index)

    def _diff_lists_lcs(
        self,
        expected: list[Any],
        actual: list[Any],
        path: str,
    ) -> list[Change]:
        lcs_indices = compute_lcs_indices(expected, actual)
        changes: list[Change] = []
        expected_in_lcs = {i for i, _ in lcs_indices}
        actual_in_lcs = {j for _, j in lcs_indices}

        for i, val in enumerate(expected):
            if i not in expected_in_lcs:
                changes.append(KeyRemoved(f"{path}[{i}]", val))

        for j, val in enumerate(actual):
            if j not in actual_in_lcs:
                changes.append(KeyAdded(f"{path}[{j}]", val))

        for i, j in lcs_indices:
            changes.extend(self._compute_changes(expected[i], actual[j], f"{path}[{j}]"))

        return changes

    def _diff_lists_index(
        self,
        expected: list[Any],
        actual: list[Any],
        path: str,
    ) -> list[Change]:
        changes: list[Change] = []
        max_len = max(len(expected), len(actual))

        for i in range(max_len):
            child_path = f"{path}[{i}]"
            if i >= len(expected):
                changes.append(KeyAdded(child_path, actual[i]))
            elif i >= len(actual):
                changes.append(KeyRemoved(child_path, expected[i]))
            else:
                changes.extend(self._compute_changes(expected[i], actual[i], child_path))

        return changes

    def _format_changes(self, changes: list[Change]) -> str:
        """Render the structured summary section shown before the full diff."""
        count = len(changes)
        noun = "change" if count == 1 else "changes"
        lines = [f"{count} {noun}:", ""]
        for change in changes:
            lines.append(self._format_single_change(change))
        return "\n".join(lines)

    def _format_single_change(self, change: Change) -> str:
        if isinstance(change, ValueChanged):
            old_repr = self._truncate(self._json_repr(change.old_value))
            new_repr = self._truncate(self._json_repr(change.new_value))
            return f"  CHANGED  {change.path}    {old_repr} -> {new_repr}"

        if isinstance(change, KeyAdded):
            val_repr = self._truncate(self._json_repr(change.value))
            return f"  ADDED    {change.path}    {val_repr}"

        if isinstance(change, KeyRemoved):
            val_repr = self._truncate(self._json_repr(change.value))
            return f"  REMOVED  {change.path}    {val_repr}"

        if isinstance(change, TypeChanged):
            old_type = type(change.old_value).__name__
            new_type = type(change.new_value).__name__
            old_repr = self._truncate(self._json_repr(change.old_value))
            new_repr = self._truncate(self._json_repr(change.new_value))
            return (
                f"  TYPE     {change.path}    "
                f"{old_repr} ({old_type}) -> {new_repr} ({new_type})"
            )

        return f"  UNKNOWN  {change}"

    def _json_repr(self, value: Any) -> str:
        """Return a compact JSON-style representation suitable for diff output."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return json.dumps(value)
        if isinstance(value, (int, float)):
            return json.dumps(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _truncate(self, s: str) -> str:
        """Truncate long value renderings to keep summaries readable."""
        if len(s) <= self._value_truncate_length:
            return s
        return s[: self._value_truncate_length - 3] + "..."
