from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SnapshotKey:
    """Uniquely identifies a single snapshot within the project."""

    module: str
    class_name: str | None
    test_name: str
    snapshot_name: str


@dataclass(frozen=True, slots=True)
class AssertionDiagnostics:
    """Lightweight runtime metadata attached to assertion outcomes."""

    serializer_name: str
    serializer_priority: int | None
    serializer_forced: bool
    repr_fallback_used: bool
    sanitizer_names: tuple[str, ...]
    sanitizer_profile: str
    diff_mode: str
    effective_diff_mode: str | None = None
    diff_fallback_reason: str | None = None
    snapshot_path: Path | None = None


@dataclass(frozen=True, slots=True)
class PolicyFinding:
    """Machine-readable policy observation for reports and diagnostics."""

    code: str
    message: str
    severity: str = "warning"
    test_id: str | None = None
    snapshot_name: str | None = None
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class DiffRenderResult:
    """Rendered diff text plus metadata about the render path."""

    text: str
    mode: str
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    """Represents a stored snapshot (key + serialized content)."""

    key: SnapshotKey
    content: str


class SnapshotResult(Enum):
    """Outcome of a snapshot comparison."""

    MATCH = "match"
    MISMATCH = "mismatch"
    CREATED = "created"
    UPDATED = "updated"


@dataclass(frozen=True, slots=True)
class MismatchDetail:
    """Carries diff information when a snapshot comparison fails."""

    key: SnapshotKey
    expected: str
    actual: str
    diff: str
    diagnostics: AssertionDiagnostics | None = None
