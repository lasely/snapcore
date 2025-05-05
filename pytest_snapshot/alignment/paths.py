"""Path normalization and matching utilities for alignment rules.

Alignment rules use a JSONPath-subset notation.  This module normalizes
user-supplied paths to a canonical form and provides helpers for matching
runtime paths against registered rule paths.
"""

from __future__ import annotations

import re

_INDEX_RE = re.compile(r"\[\d+\]")
_BRACKET_RE = re.compile(r"\[[^\]]+\]")


def normalize_path(path: str) -> str:
    """Normalize a user-supplied or runtime JSON path to canonical form.

    Canonical form:
    - Always starts with ``$``
    - Uses dot notation for dict keys: ``$.users``
    - Preserves ``[*]`` for wildcard list traversal: ``$.users[*].orders``
    - No trailing dots or empty segments

    Examples::

        normalize_path("users")           -> "$.users"
        normalize_path("$.users")         -> "$.users"
        normalize_path("$users")          -> "$.users"
        normalize_path("$.users[*]")      -> "$.users[*]"
        normalize_path("")                -> "$"
        normalize_path("$")              -> "$"
    """
    if not path or path == "$":
        return "$"

    if path.startswith("$."):
        body = path[2:]
    elif path.startswith("$"):
        body = path[1:]
    else:
        body = path

    body = body.strip(".")
    if not body:
        return "$"

    return "$." + body


def generalize_indices(path: str) -> str:
    """Replace concrete list indices with ``[*]`` wildcards.

    Used to convert runtime paths (``$.regions[3].orders``) into
    pattern-matchable form (``$.regions[*].orders``).
    """
    return _INDEX_RE.sub("[*]", path)


def generalize_brackets(path: str) -> str:
    """Replace ALL bracket expressions (except ``[*]``) with ``[*]`` wildcards.

    Used to convert aligned paths that contain entity-label brackets
    (e.g., ``$.regions[name="US"].orders``) into pattern-matchable form
    (``$.regions[*].orders``).  This is a superset of ``generalize_indices``
    that also handles composite key labels and string-valued labels.
    """
    return _BRACKET_RE.sub("[*]", path)
