"""Runtime services used by the snapshot assertion facade.

The module contains the preparation pipeline for serializer selection,
sanitization, diagnostics assembly, and diff metadata so the facade can remain
focused on control flow rather than low-level mechanics.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .config import SnapshotConfig
from .exceptions import SerializerNotFoundError
from .models import AssertionDiagnostics, DiffRenderResult, PolicyFinding, SnapshotKey
from .policy import (
    build_repr_fallback_blocked_finding,
    build_repr_fallback_warning_finding,
)
from .protocols import DiffRenderer, DiffRendererWithMetadata, StorageBackend
from .sanitizers import SanitizerRegistry
from .sanitizers.json_masks import JsonMaskApplicator
from .serializers import SerializerRegistry

if TYPE_CHECKING:
    from .alignment.registry import AlignmentRegistry
    from .review.collector import SnapshotCollector


@dataclass(frozen=True, slots=True)
class PreparedAssertion:
    """Represent serialized input before persistence and comparison decisions."""

    key: SnapshotKey
    actual: str
    diagnostics: AssertionDiagnostics
    snapshot_path: Path | None


class AssertionRuntime:
    """Prepare assertion inputs and emit diagnostics-related side effects."""

    def __init__(
        self,
        config: SnapshotConfig,
        serializer_registry: SerializerRegistry,
        sanitizer_registry: SanitizerRegistry,
        storage: StorageBackend,
        differ: DiffRenderer,
        *,
        collector: SnapshotCollector | None = None,
        json_mask_applicator: JsonMaskApplicator | None = None,
    ) -> None:
        self._config = config
        self._serializer_registry = serializer_registry
        self._sanitizer_registry = sanitizer_registry
        self._storage = storage
        self._differ = differ
        self._collector = collector
        self._json_mask_applicator = json_mask_applicator

    def prepare(self, *, key: SnapshotKey, value: Any) -> PreparedAssertion:
        """Serialize, sanitize, and annotate a value for snapshot comparison."""
        snapshot_path = self._resolve_storage_path(key)
        self._record_inventory(key, snapshot_path)

        forced_serializer = self._config.default_serializer_name is not None
        if self._config.default_serializer_name is not None:
            serializer_entry = self._serializer_registry.resolve_by_name_entry(
                self._config.default_serializer_name
            )
            if serializer_entry is None:
                raise SerializerNotFoundError(type(value))
            serializer, serializer_priority = serializer_entry
        else:
            serializer, serializer_priority = self._serializer_registry.resolve_entry(value)

        repr_fallback_used = serializer.name == "repr" and not forced_serializer
        self._apply_repr_policy(
            serializer_name=serializer.name,
            value=value,
            forced=forced_serializer,
            key=key,
            snapshot_path=snapshot_path,
        )

        actual = serializer.serialize(value)
        if self._json_mask_applicator is not None and serializer.name == "json":
            actual = self._json_mask_applicator.apply(actual)
        self._sanitizer_registry.reset_stateful()
        actual, sanitizer_names, sanitizer_counts = (
            self._sanitizer_registry.apply_with_diagnostics(actual)
        )

        diagnostics = AssertionDiagnostics(
            serializer_name=serializer.name,
            serializer_priority=serializer_priority,
            serializer_forced=forced_serializer,
            repr_fallback_used=repr_fallback_used,
            sanitizer_names=tuple(sanitizer_names),
            sanitizer_profile=self._config.sanitizer_profile,
            diff_mode=self._config.diff_mode,
            sanitizer_counts=tuple(sanitizer_counts.items()) if sanitizer_counts else None,
            snapshot_path=snapshot_path,
        )
        return PreparedAssertion(
            key=key,
            actual=actual,
            diagnostics=diagnostics,
            snapshot_path=snapshot_path,
        )

    def render_diff(
        self,
        *,
        expected: str,
        actual: str,
        diagnostics: AssertionDiagnostics,
        alignment_registry: AlignmentRegistry | None = None,
    ) -> tuple[str, AssertionDiagnostics]:
        """Render a diff and merge the render metadata into diagnostics."""
        diff_result = self._render_diff(
            expected=expected, actual=actual,
            alignment_registry=alignment_registry,
        )
        return diff_result.text, AssertionDiagnostics(
            serializer_name=diagnostics.serializer_name,
            serializer_priority=diagnostics.serializer_priority,
            serializer_forced=diagnostics.serializer_forced,
            repr_fallback_used=diagnostics.repr_fallback_used,
            sanitizer_names=diagnostics.sanitizer_names,
            sanitizer_profile=diagnostics.sanitizer_profile,
            diff_mode=diagnostics.diff_mode,
            sanitizer_counts=diagnostics.sanitizer_counts,
            effective_diff_mode=diff_result.mode,
            diff_fallback_reason=diff_result.fallback_reason,
            snapshot_path=diagnostics.snapshot_path,
        )

    def record_policy_finding(self, finding: PolicyFinding) -> None:
        """Forward a policy finding into the active session collector when present."""
        if self._collector is not None:
            self._collector.record_policy_finding(finding)

    def _apply_repr_policy(
        self,
        *,
        serializer_name: str,
        value: Any,
        forced: bool,
        key: SnapshotKey,
        snapshot_path: Path | None,
    ) -> None:
        if serializer_name != "repr" or forced:
            return

        type_name = type(value).__qualname__
        if self._config.repr_policy == "forbid":
            self.record_policy_finding(
                build_repr_fallback_blocked_finding(
                    key,
                    type_name=type_name,
                    path=snapshot_path,
                )
            )
            raise SerializerNotFoundError(type(value))

        if self._config.repr_policy == "warn":
            self.record_policy_finding(
                build_repr_fallback_warning_finding(
                    key,
                    type_name=type_name,
                    path=snapshot_path,
                )
            )
            warnings.warn(
                (
                    f"Falling back to repr() serializer for type "
                    f"{type_name}. "
                    "Register a custom serializer or change snapshot_repr_policy."
                ),
                UserWarning,
                stacklevel=4,
            )

    def _resolve_storage_path(self, key: SnapshotKey) -> Path | None:
        """Ask the storage backend for a resolved path when supported."""
        path_for = getattr(self._storage, "path_for", None)
        if callable(path_for):
            return path_for(key)
        return None

    def _record_inventory(self, key: SnapshotKey, snapshot_path: Path | None) -> None:
        """Record active snapshot usage for prune and reporting workflows."""
        if self._collector is None or snapshot_path is None:
            return
        self._collector.record_snapshot(key, snapshot_path)

    def _render_diff(
        self,
        *,
        expected: str,
        actual: str,
        alignment_registry: AlignmentRegistry | None = None,
    ) -> DiffRenderResult:
        """Render a diff using metadata-aware renderer APIs when available."""
        from .diff.structural import StructuralDiffRenderer

        if isinstance(self._differ, StructuralDiffRenderer) and alignment_registry is not None:
            return self._differ.render_with_metadata(
                expected, actual, alignment_registry=alignment_registry,
            )
        if isinstance(self._differ, DiffRendererWithMetadata):
            return self._differ.render_with_metadata(expected, actual)
        return DiffRenderResult(
            text=self._differ.render(expected=expected, actual=actual),
            mode=self._config.diff_mode,
        )
