"""Helpers for building policy findings and stable test identifiers.

Keeping finding construction in one module prevents duplicated error codes and
message templates across the facade, runtime, plugin, and reporting layers.
"""

from __future__ import annotations

from pathlib import Path

from .models import PolicyFinding, SnapshotKey


def format_test_id(key: SnapshotKey) -> str:
    """Return the canonical pytest-style test identifier for ``key``."""
    if key.class_name:
        return f"{key.module}::{key.class_name}::{key.test_name}"
    return f"{key.module}::{key.test_name}"


def build_missing_snapshot_blocked_finding(
    key: SnapshotKey,
    *,
    path: Path | None,
) -> PolicyFinding:
    """Create a finding describing a blocked baseline creation event."""
    return PolicyFinding(
        code="missing_snapshot_blocked",
        message=f"Missing snapshot blocked by policy for {format_test_id(key)} / {key.snapshot_name}",
        severity="error",
        test_id=format_test_id(key),
        snapshot_name=key.snapshot_name,
        path=path,
    )


def build_repr_fallback_blocked_finding(
    key: SnapshotKey,
    *,
    type_name: str,
    path: Path | None,
) -> PolicyFinding:
    """Create a finding for a forbidden ``repr`` fallback decision."""
    return PolicyFinding(
        code="repr_fallback_blocked",
        message=f"repr fallback blocked for type {type_name} in {format_test_id(key)} / {key.snapshot_name}",
        severity="error",
        test_id=format_test_id(key),
        snapshot_name=key.snapshot_name,
        path=path,
    )


def build_repr_fallback_warning_finding(
    key: SnapshotKey,
    *,
    type_name: str,
    path: Path | None,
) -> PolicyFinding:
    """Create a warning-level finding for allowed ``repr`` fallback usage."""
    return PolicyFinding(
        code="repr_fallback_warning",
        message=f"repr fallback used for type {type_name} in {format_test_id(key)} / {key.snapshot_name}",
        severity="warning",
        test_id=format_test_id(key),
        snapshot_name=key.snapshot_name,
        path=path,
    )


def build_orphan_policy_findings(orphan_paths: list[Path]) -> list[PolicyFinding]:
    """Create one warning finding per orphan snapshot path."""
    return [
        PolicyFinding(
            code="orphan_snapshot_found",
            message=f"Orphan snapshot found: {path}",
            severity="warning",
            path=path,
        )
        for path in orphan_paths
    ]
