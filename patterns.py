"""Shared regex patterns for detection and sanitization.

Centralizes commonly used patterns (UUID, ISO timestamps) so that
the intelligence profiler and sanitizer modules stay in sync.
Detection patterns are intentionally broader than sanitization
patterns: the profiler uses the broad variants to flag candidates,
while sanitizers use strict variants for safe replacement.
"""

from __future__ import annotations

import re


UUID_DETECT_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

UUID_V4_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)


ISO_TIMESTAMP_DETECT_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
)

DATETIME_FULL_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?"
)
