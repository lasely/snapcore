"""Session-scoped collection models for review and diagnostics workflows.

The collector aggregates pending snapshot changes, touched paths, and policy
findings across a pytest run so review and reporting layers can operate on one
coherent session state object.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import AssertionDiagnostics, PolicyFinding, SnapshotKey


class ChangeType(Enum):
    """Enumerate reviewable snapshot change categories."""

    CREATED = "created"
    MODIFIED = "modified"


@dataclass(frozen=True, slots=True)
class PendingChange:
    """Represent one snapshot addition or modification awaiting review."""

    key: SnapshotKey
    expected: str | None
    actual: str
    diff: str
    change_type: ChangeType
    diagnostics: AssertionDiagnostics | None = None


class SnapshotCollector:
    """Aggregate reviewable snapshot state for the duration of one test session."""

    def __init__(self) -> None:
        self._pending: list[PendingChange] = []
        self._touched_keys: set[SnapshotKey] = set()
        self._touched_paths: set[Path] = set()
        self._policy_findings: list[PolicyFinding] = []

    def add(self, change: PendingChange) -> None:
        """Append a pending snapshot change to the current session."""
        self._pending.append(change)

    def record_snapshot(self, key: SnapshotKey, path: Path) -> None:
        """Record that ``key`` resolved to ``path`` during the current session."""
        self._touched_keys.add(key)
        self._touched_paths.add(path.resolve())

    def record_policy_finding(self, finding: PolicyFinding) -> None:
        """Record a policy-related observation discovered during assertion flow."""
        self._policy_findings.append(finding)

    @property
    def pending(self) -> list[PendingChange]:
        """Return a defensive copy of the pending change list."""
        return list(self._pending)

    @property
    def has_changes(self) -> bool:
        """Return whether the current session produced reviewable changes."""
        return len(self._pending) > 0

    @property
    def touched_keys(self) -> set[SnapshotKey]:
        """Return snapshot keys observed during the current session."""
        return set(self._touched_keys)

    @property
    def touched_paths(self) -> set[Path]:
        """Return resolved snapshot paths observed during the current session."""
        return set(self._touched_paths)

    @property
    def policy_findings(self) -> list[PolicyFinding]:
        """Return a defensive copy of collected policy findings."""
        return list(self._policy_findings)

    def __len__(self) -> int:
        """Return the number of pending snapshot changes in the session."""
        return len(self._pending)
