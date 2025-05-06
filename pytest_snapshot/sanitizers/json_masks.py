"""Scoped JSON masking for targeted field replacement.

Applies path-based masks to JSON-serialized text, replacing specific
field values with named placeholders.  This avoids regex overreach
when the noisy fields are known in advance.

Supported path selectors::

    $.field              -- top-level key
    $.nested.field       -- nested key traversal
    $.items[*].id        -- wildcard over list elements
    $.data[*].items[*].x -- nested wildcards
"""

from __future__ import annotations

import json
from typing import Any


class JsonMaskApplicator:
    """Apply path-based masks to JSON text.

    Parameters
    ----------
    masks:
        Mapping of path selectors to replacement strings.
        Example: ``{"$.meta.generated_at": "<DATETIME>", "$.users[*].id": "<USER_ID>"}``
    """

    def __init__(self, masks: dict[str, str]) -> None:
        self._masks = masks
        self._parsed = [(_parse_path(p), v) for p, v in masks.items()]

    def apply(self, text: str) -> str:
        """Parse JSON, apply masks, re-serialize.

        Returns the text unchanged if it is not valid JSON or if
        no masks match.
        """
        if not self._masks:
            return text

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text

        for segments, replacement in self._parsed:
            _apply_mask(data, segments, replacement)

        return json.dumps(data, indent=2, ensure_ascii=False)

    @property
    def mask_count(self) -> int:
        return len(self._masks)


def _parse_path(path: str) -> list[str | None]:
    """Parse a path selector into traversal segments.

    ``$`` is stripped.  ``[*]`` becomes ``None`` (wildcard marker).
    Dot-separated keys become string segments.

    Examples::

        "$.meta.generated_at"  -> ["meta", "generated_at"]
        "$.users[*].id"        -> ["users", None, "id"]
        "$.data[*].items[*].x" -> ["data", None, "items", None, "x"]
    """
    if path.startswith("$."):
        path = path[2:]
    elif path.startswith("$"):
        path = path[1:]

    segments: list[str | None] = []
    for part in path.split("."):
        if part.endswith("[*]"):
            segments.append(part[:-3])
            segments.append(None)
        else:
            segments.append(part)
    return segments


def _apply_mask(data: Any, segments: list[str | None], replacement: str) -> None:
    """Recursively walk *data* following *segments* and replace leaf values."""
    if not segments:
        return

    head, rest = segments[0], segments[1:]

    if head is None:
        # Wildcard: iterate list elements
        if isinstance(data, list):
            for item in data:
                _apply_mask(item, rest, replacement)
        return

    if isinstance(data, dict) and head in data:
        if not rest:
            # Leaf: replace value
            data[head] = replacement
        else:
            _apply_mask(data[head], rest, replacement)
