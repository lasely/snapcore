"""Behavioral protocols shared across the snapshot package.

The protocols define the minimal collaboration surface for serializers,
sanitizers, storage backends, and diff renderers. They keep the implementation
decoupled without introducing an unnecessarily complex plugin framework.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .models import DiffRenderResult, SnapshotKey


class Serializer(Protocol):
    """Protocol implemented by values-to-text serializer objects."""

    @property
    def name(self) -> str: ...

    def can_handle(self, value: Any) -> bool: ...

    def serialize(self, value: Any) -> str: ...


class Sanitizer(Protocol):
    """Protocol implemented by text post-processors applied after serialization."""

    @property
    def name(self) -> str: ...

    def sanitize(self, text: str) -> str: ...


@runtime_checkable
class StatefulSanitizer(Protocol):
    """Protocol for sanitizers that keep per-assertion mutable matching state."""

    @property
    def name(self) -> str: ...

    def sanitize(self, text: str) -> str: ...

    def reset(self) -> None: ...


class StorageBackend(Protocol):
    """Protocol for snapshot persistence backends."""

    def read(self, key: SnapshotKey) -> str | None: ...

    def write(self, key: SnapshotKey, content: str) -> None: ...

    def delete(self, key: SnapshotKey) -> None: ...

    def list_files(self) -> list[Path]: ...


class DiffRenderer(Protocol):
    """Protocol for renderers that explain snapshot mismatches."""

    def render(self, expected: str, actual: str) -> str: ...


@runtime_checkable
class DiffRendererWithMetadata(DiffRenderer, Protocol):
    """Extended diff renderer that also provides render metadata.

    Implementations return a ``DiffRenderResult`` carrying the rendered text
    together with the effective diff mode and an optional fallback reason.
    The base ``render`` method is still required for backwards compatibility.
    """

    def render_with_metadata(self, expected: str, actual: str) -> DiffRenderResult: ...
