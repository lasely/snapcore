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
from ..patterns import ISO_TIMESTAMP_DETECT_RE, UUID_DETECT_RE
from .models import InstabilityFinding, PathVolatility, RunObservation

if TYPE_CHECKING:
    from .models import ObservedPathValue

# -- Epoch range for numeric timestamp detection -----------------------------

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

    def profile(
        self,
        observations: list[RunObservation],
        *,
        total_runs: int | None = None,
    ) -> ProfileResult:
        """Analyze observations for one SnapshotKey and return findings.

        Parameters
        ----------
        observations:
            RunObservation records for one snapshot target.
        total_runs:
            Actual number of profile iterations.  When provided, missing
            iterations (where ``assert_match`` did not fire) produce
            absence markers.  Defaults to ``len(observations)``.
        """
        if not observations:
            return ProfileResult(path_volatilities=(), findings=())

        total_runs = total_runs if total_runs is not None else len(observations)
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
        vol_by_path: dict[str, PathVolatility] = {}
        for path in sorted(path_data.keys()):
            entries = path_data[path]
            vol = self._compute_volatility(path, entries, total_runs)
            vol_by_path[path] = vol

        # Post-process: order_volatile is only valid when content is stable.
        # If [__content] sibling is also volatile, reclassify [__order] as
        # value_volatile (content changed, not just reorder).
        self._reclassify_order_paths(vol_by_path, path_data, total_runs)

        # Filter out internal [__content] paths — they are profiler-internal
        # and must not appear in user-facing output.
        volatilities: list[PathVolatility] = []
        for path in sorted(vol_by_path.keys()):
            if path.endswith("[__content]"):
                continue
            volatilities.append(vol_by_path[path])

        # Emit findings (also excluding [__content] paths)
        for vol in volatilities:
            entries = path_data[vol.path]
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
        """Group path values across runs, injecting absence markers.

        Multiple list elements that generalize to the same path (e.g.,
        ``$.items[*].name``) are accumulated into a multiset per run,
        preserving multiplicity so that ``[1,1,2]`` and ``[1,2,2]``
        are distinguishable.
        """
        # Collect all paths and their per-run values (list, not single)
        path_runs: dict[str, dict[int, list[ObservedPathValue]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for obs in observations:
            for pv in obs.path_values:
                path_runs[pv.path][obs.run_index].append(pv)

        # Build per-path entry lists with absence markers.
        # Iterate over the full range of profile runs, not just observed ones,
        # so that runs where assert_match() didn't fire produce absence markers.
        result: dict[str, list[_PathEntry]] = {}
        run_indices = list(range(total_runs))

        for path in sorted(path_runs.keys()):
            entries: list[_PathEntry] = []
            run_map = path_runs[path]
            for ri in run_indices:
                pvs = run_map.get(ri)
                if pvs:
                    # Build multiset of hashes (preserves multiplicity)
                    hash_counter = Counter(pv.value_hash for pv in pvs)
                    value_hashes = tuple(sorted(hash_counter.items()))
                    # Collect all types observed at this path in this run
                    value_types = tuple(sorted({pv.value_type for pv in pvs}))
                    # Representative values for pattern detection
                    rep = pvs[0]
                    entries.append(_PathEntry(
                        run_index=ri,
                        value_hash=rep.value_hash,
                        value_hashes=value_hashes,
                        value_type=rep.value_type,
                        value_types=value_types,
                        value_repr=rep.value_repr,
                        is_present=True,
                    ))
                else:
                    entries.append(_PathEntry(
                        run_index=ri,
                        value_hash="",
                        value_hashes=(),
                        value_type="",
                        value_types=(),
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

        # Distinct value multisets across runs.  Each run's value_hashes is
        # a canonical multiset tuple; we count how many distinct multisets appear.
        distinct_multisets = set(e.value_hashes for e in present_entries)
        distinct_values = len(distinct_multisets)

        # Type changes: compare per-run type-sets against the mode type-set.
        # This catches mixed types under generalized list paths.
        type_set_counter: Counter[tuple[str, ...]] = Counter(
            e.value_types for e in present_entries
        )
        mode_types = type_set_counter.most_common(1)[0][0] if type_set_counter else ()
        type_changes = sum(1 for e in present_entries if e.value_types != mode_types)

        # Value changes: adjacent pairs with different multisets
        value_changes = 0
        sorted_present = sorted(present_entries, key=lambda e: e.run_index)
        for i in range(1, len(sorted_present)):
            if sorted_present[i].value_hashes != sorted_present[i - 1].value_hashes:
                value_changes += 1

        # Order changes: only for synthetic __order__ paths
        order_changes = 0
        if path.endswith("[__order]"):
            order_changes = value_changes

        # Classify
        volatility_class = self._classify(
            presence_count=presence_count,
            total_runs=total_runs,
            distinct_values=distinct_values,
            type_changes=type_changes,
            value_changes=value_changes,
            is_order_path=path.endswith("[__order]"),
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

    @staticmethod
    def _reclassify_order_paths(
        vol_by_path: dict[str, PathVolatility],
        path_data: dict[str, list[_PathEntry]],
        total_runs: int,
    ) -> None:
        """Reclassify order_volatile when content also changed.

        ``order_volatile`` is only valid when the sibling ``[__content]``
        path is stable (same multiset across runs).  If content changed,
        the order hash change is a side effect of content change, not a
        genuine reorder.  In that case, reclassify as ``value_volatile``.
        """
        for path, vol in list(vol_by_path.items()):
            if not path.endswith("[__order]"):
                continue
            if vol.volatility_class != "order_volatile":
                continue
            content_path = path.replace("[__order]", "[__content]")
            content_vol = vol_by_path.get(content_path)
            if content_vol is not None and content_vol.volatility_class != "stable":
                # Content changed — this is not a true reorder.
                # Rebuild PathVolatility with value_volatile classification.
                vol_by_path[path] = PathVolatility(
                    path=vol.path,
                    total_runs=vol.total_runs,
                    distinct_values=vol.distinct_values,
                    presence_count=vol.presence_count,
                    type_changes=vol.type_changes,
                    value_changes=vol.value_changes,
                    order_changes=0,
                    volatility_class="value_volatile",
                    confidence=vol.confidence,
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
        # Base confidence scales linearly from 0.0 to 1.0 over 5 runs.
        # 5 runs is the default --snapshot-profile-runs value and provides
        # enough adjacent-pair comparisons (4) for reliable classification.
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

        # Timestamp pattern (strings matching ISO-8601).
        # 80% threshold: allows 1 non-matching value in 5 runs (e.g., a null
        # that got serialized as a placeholder string in one run).
        if all(t == "str" for t in types):
            ts_matches = sum(1 for r in reprs if ISO_TIMESTAMP_DETECT_RE.search(r))
            if ts_matches >= len(reprs) * 0.8:
                findings.append(build_timestamp_pattern_finding(
                    path=vol.path,
                    total_runs=total_runs,
                    match_count=ts_matches,
                    confidence=min(vol.confidence, ts_matches / len(reprs)),
                ))

        # UUID pattern
        if all(t == "str" for t in types):
            uuid_matches = sum(1 for r in reprs if UUID_DETECT_RE.search(r))
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
                # Parse numeric values from repr.  value_repr for int/float
                # types is never truncated in practice (numeric reprs are always
                # well under the 120-char limit).  If parsing fails (e.g., an
                # unexpected repr format), the except clause silently skips
                # numeric pattern detection — acceptable degradation.
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
    """Internal intermediate representation for one path observation.

    For generalized list paths (e.g., ``$.items[*].name``), multiple
    elements may map to the same path in one run.  ``value_hashes``
    stores the canonical multiset ``tuple(sorted(Counter(hashes).items()))``
    so that ``[1,1,2]`` and ``[1,2,2]`` are distinguishable.
    ``value_types`` stores all distinct types observed in this run.

    ``value_hash``, ``value_type``, and ``value_repr`` are representative
    values (from the first element) used for pattern detection display.
    """

    run_index: int
    value_hash: str
    value_hashes: tuple[tuple[str, int], ...]
    value_type: str
    value_types: tuple[str, ...]
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
