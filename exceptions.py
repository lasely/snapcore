"""Exception hierarchy and formatting helpers for snapshot failures.

The module centralizes user-facing runtime errors so assertion failures,
missing baselines, and storage issues all produce consistent diagnostics.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AssertionDiagnostics, MismatchDetail, SnapshotKey


class SnapshotError(Exception):
    """Base class for package-specific runtime failures."""


class SnapshotMismatchError(SnapshotError):
    """Raised when the current serialized value differs from stored baseline."""

    def __init__(self, detail: MismatchDetail) -> None:
        self.detail = detail
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Build the human-readable mismatch message presented to the user."""
        key = self.detail.key
        location = f"{key.module}::{key.test_name}"
        if key.class_name:
            location = f"{key.module}::{key.class_name}::{key.test_name}"
        lines = [f"Snapshot mismatch for '{key.snapshot_name}' in {location}\n"]
        if self.detail.diagnostics is not None:
            lines.append(_format_diagnostics(self.detail.diagnostics))
            lines.append("")
        lines.append(self.detail.diff)
        return "\n".join(lines)


class MissingSnapshotError(SnapshotError):
    """Raised when baseline creation is blocked by active missing-snapshot policy."""

    def __init__(
        self,
        key: SnapshotKey,
        *,
        path: Path | None = None,
        policy: str = "fail",
        diagnostics: AssertionDiagnostics | None = None,
    ) -> None:
        self.key = key
        self.path = path
        self.policy = policy
        self.diagnostics = diagnostics
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Build a detailed message for a blocked baseline creation event."""
        location = f"{self.key.module}::{self.key.test_name}"
        if self.key.class_name:
            location = f"{self.key.module}::{self.key.class_name}::{self.key.test_name}"

        lines = [f"Snapshot '{self.key.snapshot_name}' is missing for {location}."]
        if self.path is not None:
            lines.append(f"Path: {self.path}")
        lines.append(f"Missing snapshot policy: {self.policy}")
        if self.diagnostics is not None:
            lines.append("")
            lines.append(_format_diagnostics(self.diagnostics))
        lines.append(
            "Run pytest --snapshot-update to create it, "
            "use --snapshot-review to review it, "
            "or change snapshot_missing_policy."
        )
        return "\n".join(lines)


class SerializerError(SnapshotError):
    """Raised when a serializer accepts a value but cannot convert it safely."""

    def __init__(self, message: str, *, value_type: type | None = None) -> None:
        self.value_type = value_type
        super().__init__(message)


class SerializerNotFoundError(SnapshotError):
    """Raised when no registered serializer can handle the provided value."""

    def __init__(self, value_type: type) -> None:
        self.value_type = value_type
        super().__init__(
            f"No serializer can handle type: {value_type.__qualname__}. "
            "Register a custom serializer or allow repr fallback."
        )


class StorageError(SnapshotError):
    """Raised when snapshot storage cannot complete an I/O operation."""

    def __init__(self, message: str, *, key: SnapshotKey | None = None) -> None:
        self.key = key
        super().__init__(message)


def _format_diagnostics(diagnostics: AssertionDiagnostics) -> str:
    """Render assertion diagnostics as a compact multi-line text block."""
    serializer_line = diagnostics.serializer_name
    if diagnostics.serializer_priority is not None:
        serializer_line += f" (priority {diagnostics.serializer_priority})"
    if diagnostics.serializer_forced:
        serializer_line += ", forced"

    sanitizers = ", ".join(diagnostics.sanitizer_names) if diagnostics.sanitizer_names else "none"
    effective_diff = diagnostics.effective_diff_mode or diagnostics.diff_mode
    diff_line = effective_diff
    if diagnostics.effective_diff_mode and diagnostics.effective_diff_mode != diagnostics.diff_mode:
        diff_line = f"{effective_diff} (requested {diagnostics.diff_mode})"

    lines = [
        "Diagnostics:",
        f"  serializer: {serializer_line}",
        f"  repr_fallback: {'yes' if diagnostics.repr_fallback_used else 'no'}",
        f"  sanitizers: {sanitizers}",
        f"  sanitizer_profile: {diagnostics.sanitizer_profile}",
        f"  diff_mode: {diff_line}",
    ]

    if diagnostics.diff_fallback_reason is not None:
        lines.append(f"  diff_fallback: {diagnostics.diff_fallback_reason}")
    if diagnostics.snapshot_path is not None:
        lines.append(f"  path: {diagnostics.snapshot_path}")
    return "\n".join(lines)
