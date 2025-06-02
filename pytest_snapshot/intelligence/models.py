"""Immutable data models for the flakiness intelligence engine.

These models define the vocabulary for cross-run stability analysis:
observations captured from profiled runs, path-level volatility metrics,
machine-readable instability findings, and actionable suggestions.

All models are frozen dataclasses with ``slots=True``, following the
project convention for immutable value objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import SnapshotKey


# ---------------------------------------------------------------------------
# Observation layer — captured during profile-mode test execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservedPathValue:
    """A single value observed at a JSON path in one profiled run.

    The extractor walks parsed JSON from ``PreparedAssertion.actual``
    (post-serialization, post-sanitization) and emits one record per
    leaf-level path.  Paths use generalized indices (``$.users[*].name``)
    so that values at the same logical path can be aggregated across runs
    even when list lengths differ.

    ``value_hash`` is a deterministic hash for quick equality comparison.
    ``value_repr`` is a truncated human-readable representation for
    diagnostics (not used for comparison).
    """

    path: str
    value_hash: str
    value_type: str
    value_repr: str
    is_present: bool = True

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("ObservedPathValue requires a non-empty path")
        if not self.value_type:
            raise ValueError("ObservedPathValue requires a non-empty value_type")


@dataclass(frozen=True, slots=True)
class RunObservation:
    """Complete observation from one profiled run of one snapshot target.

    Each profile-mode iteration produces one ``RunObservation`` per
    ``assert_match`` call.  The observation stores the serialized text
    (for fallback text-level comparison) and the extracted path-value
    pairs (for structural analysis).

    ``path_values`` may be empty when the serializer is non-JSON
    (extractor returns empty list on ``json.loads`` failure).
    """

    key: SnapshotKey
    run_index: int
    serializer_name: str
    path_values: tuple[ObservedPathValue, ...]
    raw_text: str
    timestamp: str

    def __post_init__(self) -> None:
        if self.run_index < 0:
            raise ValueError(
                f"RunObservation run_index must be >= 0, got {self.run_index}"
            )
        if not self.serializer_name:
            raise ValueError("RunObservation requires a non-empty serializer_name")


# ---------------------------------------------------------------------------
# Analysis layer — produced by the profiler
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PathVolatility:
    """Aggregated volatility metrics for one JSON path across N runs.

    The profiler computes these metrics by grouping ``ObservedPathValue``
    records across all runs for the same generalized path.

    ``volatility_class`` is one of:
    - ``"stable"``: value and presence unchanged across all runs
    - ``"value_volatile"``: value changes, type and presence stable
    - ``"presence_volatile"``: path appears/disappears across runs
    - ``"shape_volatile"``: value type changes across runs
    - ``"order_volatile"``: list child ordering changes (content stable)
    """

    path: str
    total_runs: int
    distinct_values: int
    presence_count: int
    type_changes: int
    value_changes: int
    order_changes: int
    volatility_class: str
    confidence: float

    _VALID_CLASSES = frozenset({
        "stable",
        "value_volatile",
        "presence_volatile",
        "shape_volatile",
        "order_volatile",
    })

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("PathVolatility requires a non-empty path")
        if self.total_runs < 1:
            raise ValueError(
                f"PathVolatility total_runs must be >= 1, got {self.total_runs}"
            )
        if self.volatility_class not in self._VALID_CLASSES:
            raise ValueError(
                f"Invalid volatility_class: {self.volatility_class!r}. "
                f"Must be one of {sorted(self._VALID_CLASSES)}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"PathVolatility confidence must be 0.0-1.0, got {self.confidence}"
            )


@dataclass(frozen=True, slots=True)
class InstabilityFinding:
    """Machine-readable finding about a specific path's instability.

    Modelled after ``AlignmentFinding`` and ``PolicyFinding`` for
    consistent handling in reports and CI output.  The ``code`` field
    uses a fixed vocabulary defined in ``findings.py``.
    """

    code: str
    message: str
    severity: str
    path: str
    volatility_class: str
    evidence: tuple[str, ...]
    confidence: float
    test_id: str | None = None
    snapshot_name: str | None = None

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("InstabilityFinding requires a non-empty code")
        if self.severity not in ("info", "warning", "error"):
            raise ValueError(
                f"Invalid severity: {self.severity!r}. "
                f"Must be 'info', 'warning', or 'error'"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"InstabilityFinding confidence must be 0.0-1.0, got {self.confidence}"
            )


# ---------------------------------------------------------------------------
# Suggestion layer — produced by the suggestion engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Actionable suggestion derived from instability findings.

    Each suggestion maps to a concrete user action: adding a sanitizer,
    configuring a JSON mask, or using a relational sanitizer.

    ``action_type`` is one of:
    - ``"sanitize"``: add a built-in sanitizer (uuid, datetime)
    - ``"json_mask"``: use ``snapshot_json_masks`` fixture
    - ``"relational_sanitize"``: use a relational sanitizer

    ``parameters`` carries action-specific key-value pairs
    (e.g., ``("sanitizer_type", "datetime")``).
    """

    code: str
    message: str
    action_type: str
    target_path: str
    confidence: float
    evidence_findings: tuple[str, ...]
    parameters: tuple[tuple[str, str], ...] | None = None

    _VALID_ACTIONS = frozenset({
        "sanitize",
        "json_mask",
        "relational_sanitize",
    })

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("Suggestion requires a non-empty code")
        if self.action_type not in self._VALID_ACTIONS:
            raise ValueError(
                f"Invalid action_type: {self.action_type!r}. "
                f"Must be one of {sorted(self._VALID_ACTIONS)}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Suggestion confidence must be 0.0-1.0, got {self.confidence}"
            )


# ---------------------------------------------------------------------------
# Report layer — aggregated output per snapshot target
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Complete analysis output for one profiled snapshot target.

    Groups volatility metrics, instability findings, and actionable
    suggestions.  All tuple fields use canonical ordering to ensure
    deterministic output (QUAL-002a/b):

    - ``path_volatilities``: sorted by ``(path ASC)``
    - ``findings``: sorted by ``(severity_rank ASC, path ASC, code ASC)``
    - ``suggestions``: sorted by ``(confidence DESC, target_path ASC, code ASC)``
    """

    key: SnapshotKey
    total_runs: int
    path_volatilities: tuple[PathVolatility, ...]
    findings: tuple[InstabilityFinding, ...]
    suggestions: tuple[Suggestion, ...]
    summary: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.total_runs < 1:
            raise ValueError(
                f"AnalysisReport total_runs must be >= 1, got {self.total_runs}"
            )
