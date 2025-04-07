from __future__ import annotations

from typing import Any

from ..exceptions import SerializerNotFoundError
from ..protocols import Serializer


class SerializerRegistry:
    """Priority-based registry for snapshot serializers."""

    def __init__(self) -> None:
        self._entries: list[tuple[Serializer, int]] = []

    def register(self, serializer: Serializer, *, priority: int = 0) -> None:
        """Register a serializer with explicit priority.

        Higher priority wins during resolution.
        Built-in serializers use negative priorities.
        """
        self._entries.append((serializer, priority))

    def resolve(self, value: Any) -> Serializer:
        """Find the highest-priority serializer that can handle the value.

        Raises SerializerNotFoundError if no serializer matches.
        """
        return self.resolve_entry(value)[0]

    def resolve_entry(self, value: Any) -> tuple[Serializer, int]:
        """Find the highest-priority serializer and return it with priority."""
        candidates = [
            (s, p) for s, p in self._entries if s.can_handle(value)
        ]
        if not candidates:
            raise SerializerNotFoundError(type(value))
        candidates.sort(key=lambda entry: entry[1], reverse=True)
        return candidates[0]

    def resolve_by_name(self, name: str) -> Serializer | None:
        """Look up a serializer by name. Returns None if not found."""
        entry = self.resolve_by_name_entry(name)
        return entry[0] if entry is not None else None

    def resolve_by_name_entry(self, name: str) -> tuple[Serializer, int] | None:
        """Look up a serializer by name together with its priority."""
        for serializer, priority in self._entries:
            if serializer.name == name:
                return serializer, priority
        return None

    def priority_of(self, name: str) -> int | None:
        """Return the configured priority for a serializer name."""
        for serializer, priority in self._entries:
            if serializer.name == name:
                return priority
        return None

    def unregister(self, name: str) -> None:
        """Remove a serializer by name. No-op if not found."""
        self._entries = [
            (s, p) for s, p in self._entries if s.name != name
        ]

    def list(self) -> list[tuple[str, int]]:
        """Return list of (name, priority) pairs in resolution order."""
        sorted_entries = sorted(self._entries, key=lambda e: e[1], reverse=True)
        return [(s.name, p) for s, p in sorted_entries]


def create_default_registry() -> SerializerRegistry:
    """Create a registry pre-populated with built-in serializers."""
    from .text import TextSerializer
    from .json import JsonSerializer
    from .repr import ReprSerializer

    registry = SerializerRegistry()
    registry.register(JsonSerializer(), priority=10)
    registry.register(TextSerializer(), priority=5)
    registry.register(ReprSerializer(), priority=-100)
    return registry
