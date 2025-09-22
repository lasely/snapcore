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

from ..patterns import DATETIME_FULL_RE, UUID_V4_RE

_UUID_V4_PATTERN = UUID_V4_RE

_DATETIME_FULL_PATTERN = DATETIME_FULL_RE
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

        RelationalSanitizer("UUID", r"[0-9a-f]{8}-...")
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


class MultiPatternRelationalSanitizer(RelationalSanitizer):
    """Relational sanitizer that applies multiple patterns in priority order.

    All patterns share a single identity mapping and counter, so the same
    raw value always gets the same number regardless of which pattern
    matched it.  Each pattern can produce its own label in the placeholder.

    Subclasses define ``_patterns`` as a sequence of ``(compiled_regex, label)``
    tuples.  Patterns are applied in order (most-specific first).
    Subclasses must also override the ``name`` property.
    """

    _patterns: tuple[tuple[re.Pattern[str], str], ...] = ()

    def __init__(self) -> None:
        self._mapping: dict[str, int] = {}
        self._counter: int = 0
        self._normalize: Callable[[str], str] | None = None

    @property
    def name(self) -> str:
        raise NotImplementedError("Subclasses must define a name property")

    def sanitize(self, text: str) -> str:
        for pattern, label in self._patterns:
            text = pattern.sub(self._make_replacer(label), text)
        return text

    def _make_replacer(self, label: str) -> Callable[[re.Match[str]], str]:
        def _replace(match: re.Match[str]) -> str:
            value = match.group(0)
            key = self._normalize(value) if self._normalize else value
            if key not in self._mapping:
                self._counter += 1
                self._mapping[key] = self._counter
            return f"<{label}:{self._mapping[key]}>"
        return _replace


class RelationalDatetimeSanitizer(MultiPatternRelationalSanitizer):
    """Replace datetimes with numbered placeholders preserving identity.

    Full datetime patterns are applied before date-only patterns so that
    ``2024-01-15T10:30:00Z`` is consumed whole instead of partially matching
    the date-only regex.
    """

    _patterns = (
        (_DATETIME_FULL_PATTERN, "DATETIME"),
        (_DATE_ONLY_PATTERN, "DATE"),
    )

    @property
    def name(self) -> str:
        return "datetime_relational"


class RelationalPathSanitizer(MultiPatternRelationalSanitizer):
    """Replace absolute paths with numbered placeholders preserving identity.

    Windows paths are matched first because their backslash separators are
    more specific than the ``/`` separator in Unix paths.
    """

    _patterns = (
        (_WINDOWS_PATH_PATTERN, "PATH"),
        (_UNIX_PATH_PATTERN, "PATH"),
    )

    @property
    def name(self) -> str:
        return "path_relational"
