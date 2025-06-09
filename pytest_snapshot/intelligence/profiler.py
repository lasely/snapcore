"""Path-level stability profiler for cross-run analysis.

The profiler compares ``RunObservation`` records from multiple profile-mode
iterations and classifies each JSON path's volatility.  It emits
``PathVolatility`` metrics and ``InstabilityFinding`` diagnostics that
the suggestion engine translates into user-facing recommendations.

The profiler is deterministic: same input → same output, regardless of
observation ordering (QUAL-002a/b).  All output collections use canonical
ordering defined in the design contract.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .findings import (
    INTEL_INSUFFICIENT_RUNS,
    INTEL_NON_JSON_SKIPPED,
    build_insufficient_runs_finding,
    build_non_json_skipped_finding,
    build_numeric_drift_finding,
    build_order_volatile_finding,
    build_presence_volatile_finding,
    build_shape_volatile_finding,
    build_stable_path_finding,
    build_timestamp_pattern_finding,
    build_uuid_pattern_finding,
    build_value_volatile_finding,
)
from .models import InstabilityFinding, PathVolatility, RunObservation

if TYPE_CHECKING:
    from .models import ObservedPathValue

# -- Pattern matchers for volatile string values ----------------------------

_ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
)
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_EPOCH_MIN = 1_000_000_000      # ~2001-09-09
_EPOCH_MAX = 10_000_000_000_000  # ~2286 (ms precision)

# -- Severity ranking for canonical sort order ------------------------------

_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True, slots=True)
class ProfileResult:
    """Output of ``PathStabilityProfiler.profile()``.

    ``path_volatilities`` sorted by ``(path ASC)``.
    ``findings`` sorted by ``(severity_rank ASC, path ASC, code ASC)``.
    """

    path_volatilities: tuple[PathVolatility, ...]
    findings: tuple[InstabilityFinding, ...]


class PathStabilityProfiler:
    """Classify path-level volatility from cross-run observations.

    Algorithm:

    1. Check preconditions (min_runs, non-JSON detection).
    2. Group ``ObservedPathValue`` records across all runs by generalized path.
    3. For paths missing in some runs, inject synthetic ``is_present=False`` records.
    4. Compute per-path volatility metrics.
    5. Classify each path: stable / value_volatile / presence_volatile /
       shape_volatile / order_volatile.
    6. Run pattern detection on volatile string paths (timestamp, UUID, epoch).
    7. Emit findings with confidence scores.
    8. Sort all output in canonical order.
    """

    def __init__(self, *, min_runs: int = 3) -> None:
        self._min_runs = min_runs

    def profile(self, observations: list[RunObservation]) -> ProfileResult:
        """Analyze observations for one SnapshotKey and return findings."""
        if not observations:
            return ProfileResult(path_volatilities=(), findings=())

        total_runs = len(observations)
        findings: list[InstabilityFinding] = []

        # Check for insufficient runs
        if total_runs < self._min_runs:
            findings.append(build_insufficient_runs_finding(
                total_runs=total_runs,
                min_runs=self._min_runs,
            ))

        # Check for non-JSON (all observations have empty path_values)
        if all(len(obs.path_values) == 0 for obs in observations):
            serializer = observations[0].serializer_name
            findings.append(build_non_json_skipped_finding(
                serializer_name=serializer,
            ))
            return ProfileResult(
                path_volatilities=(),
                findings=_sort_findings(findings),
            )

        # Group path values across runs
        path_data = self._group_paths(observations, total_runs)

        # Compute volatility metrics and classify
        volatilities: list[PathVolatility] = []
        for path in sorted(path_data.keys()):
            entries = path_data[path]
            vol = self._compute_volatility(path, entries, total_runs)
            volatilities.append(vol)

            # Emit findings based on classification
            findings.extend(
                self._findings_for_path(vol, entries, total_runs)
            )

        return ProfileResult(
            path_volatilities=tuple(sorted(volatilities, key=lambda v: v.path)),
            findings=_sort_findings(findings),
        )

    def _group_paths(
        self,
        observations: list[RunObservation],
        total_runs: int,
    ) -> dict[str, list[_PathEntry]]:
        """Group path values across runs, injecting absence markers."""
        # Collect all paths and their per-run values
        path_runs: dict[str, dict[int, ObservedPathValue]] = defaultdict(dict)
        for obs in observations:
            for pv in obs.path_values:
                path_runs[pv.path][obs.run_index] = pv

        # Build per-path entry lists with absence markers
        result: dict[str, list[_PathEntry]] = {}
        run_indices = sorted({obs.run_index for obs in observations})

        for path in sorted(path_runs.keys()):
            entries: list[_PathEntry] = []
            run_map = path_runs[path]
            for ri in run_indices:
                if ri in run_map:
                    pv = run_map[ri]
                    entries.append(_PathEntry(
                        run_index=ri,
                        value_hash=pv.value_hash,
                        value_type=pv.value_type,
                        value_repr=pv.value_repr,
                        is_present=pv.is_present,
                    ))
                else:
                    entries.append(_PathEntry(
                        run_index=ri,
                        value_hash="",
                        value_type="",
                        value_repr="",
                        is_present=False,
                    ))
            result[path] = entries

        return result

    def _compute_volatility(
        self,
        path: str,
        entries: list[_PathEntry],
        total_runs: int,
    ) -> PathVolatility:
        """Compute volatility metrics for one path."""
        present_entries = [e for e in entries if e.is_present]
        presence_count = len(present_entries)

        # Distinct value hashes (only from present entries)
        distinct_hashes = set(e.value_hash for e in present_entries)
        distinct_values = len(distinct_hashes)

        # Type changes: count entries with a type different from the mode
        type_counter: Counter[str] = Counter(e.value_type for e in present_entries)
        mode_type = type_counter.most_common(1)[0][0] if type_counter else ""
        type_changes = sum(1 for e in present_entries if e.value_type != mode_type)

        # Value changes: adjacent pairs with different hashes
        value_changes = 0
        sorted_present = sorted(present_entries, key=lambda e: e.run_index)
        for i in range(1, len(sorted_present)):
            if sorted_present[i].value_hash != sorted_present[i - 1].value_hash:
                value_changes += 1

        # Order changes: only for synthetic __order__ paths
        order_changes = 0
        if path.endswith(".__order__"):
            order_changes = value_changes  # Hash changes = order changes for this path

        # Classify
        volatility_class = self._classify(
            presence_count=presence_count,
            total_runs=total_runs,
            distinct_values=distinct_values,
            type_changes=type_changes,
            value_changes=value_changes,
            is_order_path=path.endswith(".__order__"),
            order_changes=order_changes,
        )

        # Confidence
        confidence = self._compute_confidence(total_runs, volatility_class, entries)

        return PathVolatility(
            path=path,
            total_runs=total_runs,
            distinct_values=distinct_values,
            presence_count=presence_count,
            type_changes=type_changes,
            value_changes=value_changes,
            order_changes=order_changes,
            volatility_class=volatility_class,
            confidence=confidence,
        )

    def _classify(
        self,
        *,
        presence_count: int,
        total_runs: int,
        distinct_values: int,
        type_changes: int,
        value_changes: int,
        is_order_path: bool,
        order_changes: int,
    ) -> str:
        """Classify a path's volatility from computed metrics."""
        if presence_count < total_runs:
            return "presence_volatile"
        if type_changes > 0:
            return "shape_volatile"
        if is_order_path and order_changes > 0:
            return "order_volatile"
        if distinct_values > 1:
            return "value_volatile"
        return "stable"

    def _compute_confidence(
        self,
        total_runs: int,
        volatility_class: str,
        entries: list[_PathEntry],
    ) -> float:
        """Compute confidence score based on run count and evidence."""
        # Base confidence scales with number of runs
        base = min(1.0, total_runs / 5.0)

        if volatility_class == "stable":
            return base

        # For volatile classifications, adjust by evidence strength
        present_entries = [e for e in entries if e.is_present]
        if len(present_entries) < 2:
            return base * 0.5

        return round(base, 4)

    def _findings_for_path(
        self,
        vol: PathVolatility,
        entries: list[_PathEntry],
        total_runs: int,
    ) -> list[InstabilityFinding]:
        """Emit findings based on a path's volatility classification."""
        findings: list[InstabilityFinding] = []

        if vol.volatility_class == "stable":
            # Don't emit stable findings — too noisy
            return findings

        if vol.volatility_class == "value_volatile":
            findings.append(build_value_volatile_finding(
                path=vol.path,
                total_runs=total_runs,
                distinct_values=vol.distinct_values,
                value_changes=vol.value_changes,
                confidence=vol.confidence,
            ))
            # Pattern detection on volatile string values
            findings.extend(self._detect_patterns(vol, entries, total_runs))

        elif vol.volatility_class == "presence_volatile":
            findings.append(build_presence_volatile_finding(
                path=vol.path,
                total_runs=total_runs,
                presence_count=vol.presence_count,
                confidence=vol.confidence,
            ))

        elif vol.volatility_class == "shape_volatile":
            findings.append(build_shape_volatile_finding(
                path=vol.path,
                total_runs=total_runs,
                type_changes=vol.type_changes,
                confidence=vol.confidence,
            ))

        elif vol.volatility_class == "order_volatile":
            findings.append(build_order_volatile_finding(
                path=vol.path,
                total_runs=total_runs,
                order_changes=vol.order_changes,
                confidence=vol.confidence,
            ))

        return findings

    def _detect_patterns(
        self,
        vol: PathVolatility,
        entries: list[_PathEntry],
        total_runs: int,
    ) -> list[InstabilityFinding]:
        """Detect timestamp/UUID/numeric patterns in volatile string values."""
        findings: list[InstabilityFinding] = []
        present = [e for e in entries if e.is_present]
        if not present:
            return findings

        reprs = [e.value_repr for e in present]
        types = [e.value_type for e in present]

        # Timestamp pattern (strings matching ISO-8601)
        if all(t == "str" for t in types):
            ts_matches = sum(1 for r in reprs if _ISO_TIMESTAMP_RE.search(r))
            if ts_matches >= len(reprs) * 0.8:
                findings.append(build_timestamp_pattern_finding(
                    path=vol.path,
                    total_runs=total_runs,
                    match_count=ts_matches,
                    confidence=min(vol.confidence, ts_matches / len(reprs)),
                ))

        # UUID pattern
        if all(t == "str" for t in types):
            uuid_matches = sum(1 for r in reprs if _UUID_RE.search(r))
            if uuid_matches >= len(reprs) * 0.8:
                findings.append(build_uuid_pattern_finding(
                    path=vol.path,
                    total_runs=total_runs,
                    match_count=uuid_matches,
                    confidence=min(vol.confidence, uuid_matches / len(reprs)),
                ))

        # Numeric drift (int/float values within a small range)
        if all(t in ("int", "float") for t in types) and len(present) >= 2:
            try:
                # Parse numeric values from repr
                nums = [float(e.value_repr) for e in present]
                min_val, max_val = min(nums), max(nums)
                # Check for epoch-like timestamps
                if all(_EPOCH_MIN <= n <= _EPOCH_MAX for n in nums):
                    findings.append(build_timestamp_pattern_finding(
                        path=vol.path,
                        total_runs=total_runs,
                        match_count=len(nums),
                        confidence=vol.confidence,
                    ))
                elif max_val - min_val > 0:
                    findings.append(build_numeric_drift_finding(
                        path=vol.path,
                        total_runs=total_runs,
                        min_value=min_val,
                        max_value=max_val,
                        confidence=vol.confidence,
                    ))
            except (ValueError, TypeError):
                pass

        return findings


# -- Internal helpers -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PathEntry:
    """Internal intermediate representation for one path observation."""

    run_index: int
    value_hash: str
    value_type: str
    value_repr: str
    is_present: bool


def _sort_findings(
    findings: list[InstabilityFinding],
) -> tuple[InstabilityFinding, ...]:
    """Sort findings in canonical order: severity_rank ASC, path ASC, code ASC."""
    return tuple(sorted(
        findings,
        key=lambda f: (_SEVERITY_RANK.get(f.severity, 99), f.path, f.code),
    ))
