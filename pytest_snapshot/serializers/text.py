from __future__ import annotations

from typing import Any


class TextSerializer:
    """Identity serializer for str values."""

    name = "text"

    def can_handle(self, value: Any) -> bool:
        return isinstance(value, str)

    def serialize(self, value: Any) -> str:
        return value
