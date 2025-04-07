from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .config import SnapshotConfig
from .exceptions import MissingSnapshotError, SnapshotError, SnapshotMismatchError
from .models import MismatchDetail, SnapshotKey
from .policy import build_missing_snapshot_blocked_finding
from .protocols import DiffRenderer, StorageBackend
from .runtime import AssertionRuntime
from .sanitizers import SanitizerRegistry
from .serializers import SerializerRegistry

if TYPE_CHECKING:
    from .review.collector import SnapshotCollector


@dataclass(frozen=True, slots=True)
class TestLocation:
    """Identifies the current test. Injected by the plugin layer."""

    __test__ = False

    module: str
    class_name: str | None
    test_name: str


class SnapshotAssertion:
    """Thin facade that orchestrates snapshot decisions for a single test."""

    def __init__(
        self,
        config: SnapshotConfig,
        serializer_registry: SerializerRegistry,
        sanitizer_registry: SanitizerRegistry,
        storage: StorageBackend,
        differ: DiffRenderer,
        *,
        test_location: TestLocation,
        collector: SnapshotCollector | None = None,
    ) -> None:
        self._config = config
        self._storage = storage
        self._test_location = test_location
        self._collector = collector
        self._runtime = AssertionRuntime(
            config,
            serializer_registry,
            sanitizer_registry,
            storage,
            differ,
            collector=collector,
        )
        self._auto_index: int = 0
        self._used_names: set[str] = set()

    @property
    def _review_mode(self) -> bool:
        return self._config.review_mode or self._config.review_ci_mode

    @property
    def _effective_missing_policy(self) -> str:
        if self._review_mode and self._collector is not None:
            return "review"
        return self._config.missing_policy

    def assert_match(
        self,
        value: Any,
        *,
        snapshot_name: str | None = None,
    ) -> None:
        """Assert that value matches the stored snapshot."""
        key = SnapshotKey(
            module=self._test_location.module,
            class_name=self._test_location.class_name,
            test_name=self._test_location.test_name,
            snapshot_name=self._resolve_name(snapshot_name),
        )
        prepared = self._runtime.prepare(key=key, value=value)

        if self._config.update_mode:
            self._storage.write(key, prepared.actual)
            return

        stored = self._storage.read(key)
        if stored is None:
            self._handle_missing_snapshot(prepared)
            return

        if stored == prepared.actual:
            return

        diff, diagnostics = self._runtime.render_diff(
            expected=stored,
            actual=prepared.actual,
            diagnostics=prepared.diagnostics,
        )

        if self._review_mode and self._collector is not None:
            from .review.collector import ChangeType, PendingChange

            self._collector.add(
                PendingChange(
                    key=key,
                    expected=stored,
                    actual=prepared.actual,
                    diff=diff,
                    change_type=ChangeType.MODIFIED,
                    diagnostics=diagnostics,
                )
            )
            return

        raise SnapshotMismatchError(
            MismatchDetail(
                key=key,
                expected=stored,
                actual=prepared.actual,
                diff=diff,
                diagnostics=diagnostics,
            )
        )

    def _handle_missing_snapshot(self, prepared) -> None:
        missing_policy = self._effective_missing_policy
        if missing_policy == "review" and self._collector is not None:
            from .review.collector import ChangeType, PendingChange

            self._collector.add(
                PendingChange(
                    key=prepared.key,
                    expected=None,
                    actual=prepared.actual,
                    diff="",
                    change_type=ChangeType.CREATED,
                    diagnostics=prepared.diagnostics,
                )
            )
            return

        if missing_policy == "review":
            raise SnapshotError(
                "Missing snapshot policy 'review' requires a SnapshotCollector."
            )

        if missing_policy == "fail":
            self._runtime.record_policy_finding(
                build_missing_snapshot_blocked_finding(
                    prepared.key,
                    path=prepared.snapshot_path,
                )
            )
            raise MissingSnapshotError(
                prepared.key,
                path=prepared.snapshot_path,
                policy=missing_policy,
                diagnostics=prepared.diagnostics,
            )

        self._storage.write(prepared.key, prepared.actual)

    def _resolve_name(self, snapshot_name: str | None) -> str:
        """Resolve snapshot name, handling auto-indexing and duplicate detection."""
        if snapshot_name is None:
            name = str(self._auto_index)
            self._auto_index += 1
        else:
            name = snapshot_name
            if not name.strip():
                raise SnapshotError("Explicit snapshot name cannot be empty or whitespace-only.")

        if name in self._used_names:
            raise SnapshotError(
                f"Duplicate snapshot name '{name}' in "
                f"{self._test_location.module}::{self._test_location.test_name}. "
                f"Each snapshot in a test must have a unique name."
            )
        self._used_names.add(name)
        return name
