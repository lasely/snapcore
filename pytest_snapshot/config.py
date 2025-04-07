"""Configuration models for pytest snapshot workflows.

This module keeps runtime options in a compact immutable dataclass so the
pytest plugin, assertion facade, and supporting services can share the same
policy set without hidden mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SnapshotConfig:
    """Immutable configuration consumed by snapshot runtime services.

    The object intentionally contains only simple values. That makes it safe to
    pass through pytest hooks, assertion helpers, and reporting layers.
    """

    snapshot_dir: Path = field(default_factory=lambda: Path("__snapshots__"))
    update_mode: bool = False
    review_mode: bool = False
    review_ci_mode: bool = False
    diff_mode: str = "text"
    default_serializer_name: str | None = None
    missing_policy: str = "create"
    repr_policy: str = "warn"
    sanitizer_profile: str = "none"
    xdist_policy: str = "fail"
