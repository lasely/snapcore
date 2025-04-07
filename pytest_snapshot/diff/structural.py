"""Structured diff rendering for JSON-compatible snapshot content.

The renderer prefers semantic change descriptions for dictionaries and lists
while retaining a unified text diff as a fallback or detailed appendix.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import DiffRenderResult
from .changes import Change, KeyAdded, KeyRemoved, TypeChanged, ValueChanged
from .lcs import compute_lcs_indices
from .text import TextDiffRenderer

_LCS_LIST_THRESHOLD = 50


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

    def render(self, expected: str, actual: str) -> str:
        """Return the formatted structural diff text for two serialized values."""
        return self.render_with_metadata(expected, actual).text

    def render_with_metadata(self, expected: str, actual: str) -> DiffRenderResult:
        """Return structural diff text together with fallback metadata."""
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
        if len(expected) <= _LCS_LIST_THRESHOLD and len(actual) <= _LCS_LIST_THRESHOLD:
            return self._diff_lists_lcs(expected, actual, path)
        return self._diff_lists_index(expected, actual, path)

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
