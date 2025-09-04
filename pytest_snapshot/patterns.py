"""Shared regex patterns for detection and sanitization.

Centralizes commonly used patterns (UUID, ISO timestamps) so that
the intelligence profiler and sanitizer modules stay in sync.
Detection patterns are intentionally broader than sanitization
patterns: the profiler uses the broad variants to flag candidates,
while sanitizers use strict variants for safe replacement.
"""

from __future__ import annotations

import re

# -- UUID patterns -----------------------------------------------------------

# Broad: matches UUID v1–v5 (any version nibble).
# Used by the intelligence profiler for *detection*.
UUID_DETECT_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# Strict: matches UUID v4 only (version nibble = 4, variant = 8/9/a/b).
# Used by sanitizers for safe replacement.
UUID_V4_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# -- Timestamp patterns ------------------------------------------------------

# Broad: matches ISO-8601 date+time prefix (no seconds required).
# Used by the intelligence profiler for *detection*.
ISO_TIMESTAMP_DETECT_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
)

# Strict: matches full ISO-8601 datetime with seconds and optional
# fractional seconds / timezone offset.
# Used by sanitizers for safe replacement.
DATETIME_FULL_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?"
)
