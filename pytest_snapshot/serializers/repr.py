from __future__ import annotations

from typing import Any


class ReprSerializer:
    """Universal fallback serializer using repr()."""

    name = "repr"

    def can_handle(self, value: Any) -> bool:
        return True

    def serialize(self, value: Any) -> str:
        return repr(value)
