"""Unified-text diff rendering helpers.

The renderer keeps mismatch output readable in terminals while also exposing a
metadata-bearing API used by diagnostics and machine-readable reports.
"""

from __future__ import annotations

import difflib
import os
import sys

from ..models import DiffRenderResult

_RED = "\033[31m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _supports_color() -> bool:
    """Return whether ANSI-colored diff output is appropriate for this process."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not hasattr(sys.stderr, "isatty"):
        return False
    return sys.stderr.isatty()


def _colorize_diff(diff_text: str) -> str:
    """Decorate a unified diff with ANSI colors for terminal presentation."""
    lines = diff_text.splitlines(keepends=True)
    colored: list[str] = []

    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            colored.append(f"{_BOLD}{_CYAN}{line}{_RESET}")
        elif line.startswith("@@"):
            colored.append(f"{_CYAN}{line}{_RESET}")
        elif line.startswith("-"):
            colored.append(f"{_RED}{line}{_RESET}")
        elif line.startswith("+"):
            colored.append(f"{_GREEN}{line}{_RESET}")
        else:
            colored.append(f"{_DIM}{line}{_RESET}")

    return "".join(colored)


class TextDiffRenderer:
    """Render snapshot mismatches as unified text diffs."""

    def __init__(self, *, context_lines: int = 3, color: bool | None = None) -> None:
        self._context_lines = context_lines
        self._color = color if color is not None else _supports_color()

    def render(self, expected: str, actual: str) -> str:
        """Return unified diff text for two serialized values."""
        return self.render_with_metadata(expected, actual).text

    def render_with_metadata(self, expected: str, actual: str) -> DiffRenderResult:
        """Return a rendered diff together with basic render metadata."""
        if expected == actual:
            return DiffRenderResult(text="", mode="text")

        expected_lines = expected.splitlines(keepends=True)
        actual_lines = actual.splitlines(keepends=True)
        diff = difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="expected (snapshot)",
            tofile="actual (current)",
            n=self._context_lines,
        )
        raw = "".join(diff)

        if self._color:
            return DiffRenderResult(text=_colorize_diff(raw), mode="text")
        return DiffRenderResult(text=raw, mode="text")
