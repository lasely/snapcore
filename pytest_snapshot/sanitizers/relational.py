"""Relational sanitizers that preserve identity relationships.

Instead of replacing all UUIDs with <UUID>, relational sanitizers assign
numbered placeholders (<UUID:1>, <UUID:2>) so that identical values get
the same number and different values get different numbers.

This catches bugs that flat sanitizers miss: if customer_id and approved_by
should be different entities but a bug makes them equal, the snapshot will
fail because <UUID:3> changed to <UUID:2>.
"""

from __future__ import annotations

import re
from typing import Callable

_UUID_V4_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)

_DATETIME_FULL_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})?"
)
_DATE_ONLY_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

_UNIX_PATH_PATTERN = re.compile(r"(?<!\w)/(?:[\w./-]+/)+[\w.-]+")
_WINDOWS_PATH_PATTERN = re.compile(
    r"[A-Z]:(?:\\|\\\\)(?:[\w. -]+(?:\\|\\\\))*[\w. -]+",
    re.IGNORECASE,
)


class RelationalSanitizer:
    """General-purpose relational sanitizer for any regex pattern.

    Assigns numbered placeholders preserving identity: same matched value
    gets the same number, different values get different numbers.
    Numbering order = first appearance in text (left to right).

    Examples::

        # Built-in patterns
        RelationalSanitizer("UUID", r"[0-9a-f]{8}-...")

        # Custom patterns
        RelationalSanitizer("JWT", r"eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+")
        RelationalSanitizer("EMAIL", r"[\\w.+-]+@[\\w-]+\\.[\\w.]+")
        RelationalSanitizer("IP", r"\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}")
        RelationalSanitizer("HASH", r"[a-f0-9]{64}")

    The ``normalize`` callback is applied to matched values before identity
    comparison.  For example, ``normalize=str.lower`` makes UUID matching
    case-insensitive.
    """

    def __init__(
        self,
        label: str,
        pattern: str | re.Pattern[str],
        *,
        normalize: Callable[[str], str] | None = None,
    ) -> None:
        self._label = label
        self._pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        self._normalize = normalize
        self._mapping: dict[str, int] = {}
        self._counter: int = 0

    @property
    def name(self) -> str:
        return f"{self._label.lower()}_relational"

    def sanitize(self, text: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            value = match.group(0)
            key = self._normalize(value) if self._normalize else value
            if key not in self._mapping:
                self._counter += 1
                self._mapping[key] = self._counter
            return f"<{self._label}:{self._mapping[key]}>"

        return self._pattern.sub(_replace, text)

    def reset(self) -> None:
        """Reset mapping. Called between assert_match() calls."""
        self._mapping.clear()
        self._counter = 0

    def __repr__(self) -> str:
        return f"RelationalSanitizer({self._label!r}, {self._pattern.pattern!r})"


class RelationalUuidSanitizer(RelationalSanitizer):
    """Replace UUIDs with numbered placeholders preserving identity.

    Same UUID value -> same number. Different UUIDs -> different numbers.
    Convenience subclass of ``RelationalSanitizer``.
    """

    def __init__(self) -> None:
        super().__init__("UUID", _UUID_V4_PATTERN, normalize=str.lower)


class RelationalDatetimeSanitizer:
    """Replace datetimes with numbered placeholders preserving identity."""

    name = "datetime_relational"

    def __init__(self) -> None:
        self._mapping: dict[str, int] = {}
        self._counter: int = 0

    def sanitize(self, text: str) -> str:
        def _replace_datetime(match: re.Match[str]) -> str:
            value = match.group(0)
            if value not in self._mapping:
                self._counter += 1
                self._mapping[value] = self._counter
            return f"<DATETIME:{self._mapping[value]}>"

        def _replace_date(match: re.Match[str]) -> str:
            value = match.group(0)
            if value not in self._mapping:
                self._counter += 1
                self._mapping[value] = self._counter
            return f"<DATE:{self._mapping[value]}>"

        text = _DATETIME_FULL_PATTERN.sub(_replace_datetime, text)
        text = _DATE_ONLY_PATTERN.sub(_replace_date, text)
        return text

    def reset(self) -> None:
        self._mapping.clear()
        self._counter = 0


class RelationalPathSanitizer:
    """Replace absolute paths with numbered placeholders preserving identity."""

    name = "path_relational"

    def __init__(self) -> None:
        self._mapping: dict[str, int] = {}
        self._counter: int = 0

    def sanitize(self, text: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            path_value = match.group(0)
            if path_value not in self._mapping:
                self._counter += 1
                self._mapping[path_value] = self._counter
            return f"<PATH:{self._mapping[path_value]}>"

        text = _WINDOWS_PATH_PATTERN.sub(_replace, text)
        text = _UNIX_PATH_PATTERN.sub(_replace, text)
        return text

    def reset(self) -> None:
        self._mapping.clear()
        self._counter = 0
