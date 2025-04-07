from __future__ import annotations

import re


class UuidSanitizer:
    """Replace UUID v4 patterns with <UUID> placeholder."""

    name = "uuid"

    _pattern = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        re.IGNORECASE,
    )

    def sanitize(self, text: str) -> str:
        return self._pattern.sub("<UUID>", text)


class DatetimeSanitizer:
    """Replace common datetime patterns with placeholders."""

    name = "datetime"

    _datetime_pattern = re.compile(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
        r"(?:\.\d+)?"
        r"(?:Z|[+-]\d{2}:\d{2})?"
    )
    _date_pattern = re.compile(
        r"\d{4}-\d{2}-\d{2}"
    )

    def sanitize(self, text: str) -> str:
        text = self._datetime_pattern.sub("<DATETIME>", text)
        text = self._date_pattern.sub("<DATE>", text)
        return text


class PathSanitizer:
    """Replace absolute filesystem paths with <PATH> placeholder."""

    name = "path"

    _unix_pattern = re.compile(r"(?<!\w)/(?:[\w./-]+/)+[\w.-]+")
    _windows_pattern = re.compile(
        r"[A-Z]:(?:\\|\\\\)(?:[\w. -]+(?:\\|\\\\))*[\w. -]+",
        re.IGNORECASE,
    )

    def sanitize(self, text: str) -> str:
        text = self._windows_pattern.sub("<PATH>", text)
        text = self._unix_pattern.sub("<PATH>", text)
        return text
