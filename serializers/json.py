from __future__ import annotations

import json
from typing import Any

from ..exceptions import SerializerError


def _strict_default(obj: Any) -> None:
    """Always-raise default function for json.dumps.

    Prevents json.dumps from silently converting unknown types via default=str.
    Forces explicit SerializerError for non-serializable types.
    """
    raise TypeError(f"Object of type {type(obj).__qualname__} is not JSON serializable")


class JsonSerializer:
    """Deterministic JSON serializer for dict, list, tuple."""

    name = "json"

    def can_handle(self, value: Any) -> bool:
        return isinstance(value, (dict, list, tuple))

    def serialize(self, value: Any) -> str:
        try:
            return json.dumps(
                value,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                default=_strict_default,
            )
        except (TypeError, ValueError) as exc:
            raise SerializerError(
                f"JsonSerializer failed to serialize {type(value).__qualname__}: {exc}. "
                "Register a custom serializer for this type.",
                value_type=type(value),
            ) from exc
