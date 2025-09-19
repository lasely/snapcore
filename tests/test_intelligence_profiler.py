"""Comprehensive unit tests for PathStabilityProfiler.

Tests cover volatility classification, pattern detection, confidence scoring,
canonical ordering, determinism (QUAL-002a/b), and edge cases.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from pytest_snapshot.intelligence.analyzer import ProfileAnalyzer
from pytest_snapshot.intelligence.collector import ObservationCollector
from pytest_snapshot.intelligence.findings import (
    INTEL_INSUFFICIENT_RUNS,
    INTEL_NON_JSON_SKIPPED,
    INTEL_NUMERIC_DRIFT,
    INTEL_ORDER_VOLATILE,
    INTEL_PRESENCE_VOLATILE,
    INTEL_SHAPE_VOLATILE,
    INTEL_TIMESTAMP_PATTERN,
    INTEL_UUID_PATTERN,
    INTEL_VALUE_VOLATILE,
)
from pytest_snapshot.intelligence.profiler import PathStabilityProfiler, ProfileResult
from pytest_snapshot.models import SnapshotKey


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_KEY = SnapshotKey(
    module="test_mod", class_name=None, test_name="test_fn", snapshot_name="0"
)


def _make_observations(
    payloads: list[str],
    serializer_name: str = "json",
    key: SnapshotKey | None = None,
) -> list:
    """Build RunObservation list from serialized payloads."""
    key = key or _DEFAULT_KEY
    collector = ObservationCollector()
    for payload in payloads:
        collector.start_run()
        collector.record(key, payload, serializer_name)
    return [
        ProfileAnalyzer._extract(raw)
        for raw in collector.observations_for(key)
    ]


def _finding_codes(result: ProfileResult) -> list[str]:
    """Extract finding codes from a ProfileResult."""
    return [f.code for f in result.findings]


def _volatility_map(result: ProfileResult) -> dict[str, str]:
    """Map path -> volatility_class from a ProfileResult."""
    return {v.path: v.volatility_class for v in result.path_volatilities}


# ---------------------------------------------------------------------------
# Stable payload
# ---------------------------------------------------------------------------


class TestStablePayload:
    """Stable JSON across multiple runs should produce no volatile findings."""

    def test_all_paths_stable(self):
        payload = json.dumps({"name": "Alice", "age": 30})
        obs = _make_observations([payload] * 5)
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        assert all(v == "stable" for v in vol_map.values())

    def test_no_volatile_findings(self):
        payload = json.dumps({"name": "Alice", "age": 30})
        obs = _make_observations([payload] * 5)
        result = PathStabilityProfiler().profile(obs)

        volatile_codes = {
            INTEL_VALUE_VOLATILE,
            INTEL_PRESENCE_VOLATILE,
            INTEL_SHAPE_VOLATILE,
            INTEL_ORDER_VOLATILE,
        }
        codes = set(_finding_codes(result))
        assert codes.isdisjoint(volatile_codes)


# ---------------------------------------------------------------------------
# Value-volatile scalar
# ---------------------------------------------------------------------------


class TestValueVolatile:
    """Changing scalar value across runs -> value_volatile classification."""

    def test_timestamp_field_classified_value_volatile(self):
        payloads = [
            json.dumps({"ts": f"2024-01-01T00:00:0{i}Z"}) for i in range(5)
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        assert vol_map["$.ts"] == "value_volatile"

    def test_value_volatile_finding_emitted(self):
        payloads = [json.dumps({"counter": i}) for i in range(5)]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_VALUE_VOLATILE in _finding_codes(result)

    def test_value_volatile_finding_has_correct_path(self):
        payloads = [json.dumps({"counter": i}) for i in range(5)]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        vol_findings = [f for f in result.findings if f.code == INTEL_VALUE_VOLATILE]
        assert any(f.path == "$.counter" for f in vol_findings)


# ---------------------------------------------------------------------------
# Presence-volatile
# ---------------------------------------------------------------------------


class TestPresenceVolatile:
    """Optional field present in some runs -> presence_volatile."""

    def test_optional_field_classified_presence_volatile(self):
        payloads = []
        for i in range(5):
            d = {"name": "Alice"}
            if i < 3:
                d["extra"] = "value"
            payloads.append(json.dumps(d))

        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        assert vol_map["$.extra"] == "presence_volatile"

    def test_presence_volatile_finding_emitted(self):
        payloads = []
        for i in range(5):
            d = {"name": "Alice"}
            if i < 3:
                d["extra"] = "value"
            payloads.append(json.dumps(d))

        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_PRESENCE_VOLATILE in _finding_codes(result)


# ---------------------------------------------------------------------------
# Shape-volatile
# ---------------------------------------------------------------------------


class TestShapeVolatile:
    """Type changes across runs -> shape_volatile."""

    def test_type_change_classified_shape_volatile(self):
        payloads = [
            json.dumps({"val": "hello"}),
            json.dumps({"val": "world"}),
            json.dumps({"val": 42}),
            json.dumps({"val": "again"}),
            json.dumps({"val": "more"}),
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        assert vol_map["$.val"] == "shape_volatile"

    def test_shape_volatile_finding_emitted(self):
        payloads = [
            json.dumps({"val": "hello"}),
            json.dumps({"val": 42}),
            json.dumps({"val": "world"}),
            json.dumps({"val": 99}),
            json.dumps({"val": "end"}),
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_SHAPE_VOLATILE in _finding_codes(result)


# ---------------------------------------------------------------------------
# Order-volatile
# ---------------------------------------------------------------------------


class TestOrderVolatile:
    """List elements same content but different order -> order_volatile."""

    def test_reordered_list_classified_order_volatile(self):
        payloads = [
            json.dumps({"items": [1, 2, 3]}),
            json.dumps({"items": [3, 1, 2]}),
            json.dumps({"items": [2, 3, 1]}),
            json.dumps({"items": [1, 3, 2]}),
            json.dumps({"items": [3, 2, 1]}),
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        # The [__order] synthetic path captures list ordering
        order_paths = [p for p in vol_map if p.endswith("[__order]")]
        assert len(order_paths) > 0
        assert vol_map[order_paths[0]] == "order_volatile"

    def test_order_volatile_finding_emitted(self):
        payloads = [
            json.dumps({"items": [1, 2, 3]}),
            json.dumps({"items": [3, 1, 2]}),
            json.dumps({"items": [2, 3, 1]}),
            json.dumps({"items": [1, 3, 2]}),
            json.dumps({"items": [3, 2, 1]}),
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_ORDER_VOLATILE in _finding_codes(result)


# ---------------------------------------------------------------------------
# Pattern detection: timestamps
# ---------------------------------------------------------------------------


class TestTimestampPattern:
    """ISO-8601 strings detected in volatile values -> INTEL_TIMESTAMP_PATTERN."""

    def test_iso_timestamp_detected(self):
        payloads = [
            json.dumps({"created": f"2024-01-{10 + i}T12:00:00Z"})
            for i in range(5)
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_TIMESTAMP_PATTERN in _finding_codes(result)

    def test_timestamp_finding_on_correct_path(self):
        payloads = [
            json.dumps({"meta": {"ts": f"2024-03-{10 + i}T08:30:00Z"}})
            for i in range(5)
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        ts_findings = [f for f in result.findings if f.code == INTEL_TIMESTAMP_PATTERN]
        assert any(f.path == "$.meta.ts" for f in ts_findings)


# ---------------------------------------------------------------------------
# Pattern detection: UUIDs
# ---------------------------------------------------------------------------


class TestUuidPattern:
    """UUID strings detected in volatile values -> INTEL_UUID_PATTERN."""

    def test_uuid_detected(self):
        payloads = [
            json.dumps({"id": str(uuid.uuid4())}) for _ in range(5)
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_UUID_PATTERN in _finding_codes(result)

    def test_uuid_finding_on_correct_path(self):
        payloads = [
            json.dumps({"request_id": str(uuid.uuid4())}) for _ in range(5)
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        uuid_findings = [f for f in result.findings if f.code == INTEL_UUID_PATTERN]
        assert any(f.path == "$.request_id" for f in uuid_findings)


# ---------------------------------------------------------------------------
# Insufficient runs
# ---------------------------------------------------------------------------


class TestInsufficientRuns:
    """Fewer than min_runs -> INTEL_INSUFFICIENT_RUNS finding."""

    def test_single_run_emits_insufficient(self):
        obs = _make_observations([json.dumps({"a": 1})])
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_INSUFFICIENT_RUNS in _finding_codes(result)

    def test_two_runs_emits_insufficient_with_default_min(self):
        obs = _make_observations([json.dumps({"a": 1})] * 2)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_INSUFFICIENT_RUNS in _finding_codes(result)

    def test_three_runs_no_insufficient_with_default_min(self):
        obs = _make_observations([json.dumps({"a": 1})] * 3)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_INSUFFICIENT_RUNS not in _finding_codes(result)


# ---------------------------------------------------------------------------
# Non-JSON serializer
# ---------------------------------------------------------------------------


class TestNonJsonSkipped:
    """Non-JSON serializer (empty path_values) -> INTEL_NON_JSON_SKIPPED."""

    def test_plain_text_emits_non_json_skipped(self):
        obs = _make_observations(
            ["not valid json"] * 5,
            serializer_name="repr",
        )
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_NON_JSON_SKIPPED in _finding_codes(result)

    def test_non_json_returns_empty_volatilities(self):
        obs = _make_observations(
            ["not valid json"] * 5,
            serializer_name="repr",
        )
        result = PathStabilityProfiler().profile(obs)

        assert result.path_volatilities == ()


# ---------------------------------------------------------------------------
# Empty observations
# ---------------------------------------------------------------------------


class TestEmptyObservations:
    """Empty observation list -> empty result."""

    def test_empty_list_returns_empty_result(self):
        result = PathStabilityProfiler().profile([])

        assert result.path_volatilities == ()
        assert result.findings == ()


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    """Confidence scales with number of runs."""

    def test_two_runs_confidence_below_one(self):
        payloads = [json.dumps({"x": i}) for i in range(2)]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler(min_runs=1).profile(obs)

        # 2 runs -> confidence = 2/5 = 0.4
        vol = next(v for v in result.path_volatilities if v.path == "$.x")
        assert vol.confidence < 1.0

    def test_five_runs_confidence_equals_one(self):
        payloads = [json.dumps({"x": i}) for i in range(5)]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        vol = next(v for v in result.path_volatilities if v.path == "$.x")
        assert vol.confidence == 1.0

    def test_stable_confidence_scales_with_runs(self):
        payload = json.dumps({"x": 1})
        obs_3 = _make_observations([payload] * 3)
        obs_5 = _make_observations([payload] * 5)

        r3 = PathStabilityProfiler(min_runs=1).profile(obs_3)
        r5 = PathStabilityProfiler(min_runs=1).profile(obs_5)

        c3 = next(v for v in r3.path_volatilities if v.path == "$.x").confidence
        c5 = next(v for v in r5.path_volatilities if v.path == "$.x").confidence
        assert c3 < c5


# ---------------------------------------------------------------------------
# Canonical ordering
# ---------------------------------------------------------------------------


class TestCanonicalOrdering:
    """Findings must be sorted by (severity_rank, path, code)."""

    def test_findings_sorted_by_severity_path_code(self):
        # Create a payload with a timestamp (info finding) and value volatile
        # (warning finding) on the same path to check sort.
        payloads = [
            json.dumps({"ts": f"2024-01-{10 + i}T00:00:00Z", "name": f"n{i}"})
            for i in range(5)
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        # Verify sorted: warnings before info
        severity_rank = {"error": 0, "warning": 1, "info": 2}
        prev = None
        for f in result.findings:
            key = (severity_rank.get(f.severity, 99), f.path, f.code)
            if prev is not None:
                assert key >= prev, (
                    f"Findings not in canonical order: {prev} > {key}"
                )
            prev = key

    def test_path_volatilities_sorted_by_path(self):
        payload = json.dumps({"z": 1, "a": 2, "m": 3})
        obs = _make_observations([payload] * 5)
        result = PathStabilityProfiler().profile(obs)

        paths = [v.path for v in result.path_volatilities]
        assert paths == sorted(paths)


# ---------------------------------------------------------------------------
# QUAL-002a: deterministic output (same input -> identical output)
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same input must produce bit-for-bit identical output (QUAL-002a)."""

    def test_qual_002a_identical_input_identical_output(self):
        payloads = [json.dumps({"x": i}) for i in range(3)]
        profiler = PathStabilityProfiler(min_runs=1)

        r1 = profiler.profile(_make_observations(payloads))
        r2 = profiler.profile(_make_observations(payloads))
        r3 = profiler.profile(_make_observations(payloads))

        assert r1 == r2 == r3

    def test_qual_002b_shuffled_observations_same_output(self):
        """Same observations in different order -> identical output (QUAL-002b)."""
        key = _DEFAULT_KEY
        payloads = [json.dumps({"x": i, "y": "stable"}) for i in range(5)]

        # Create observations normally
        obs_normal = _make_observations(payloads)

        # Create observations in reversed payload order.
        # Since ObservationCollector assigns incremental run indices,
        # we reverse the payloads to get the same data with different
        # insertion order.
        obs_reversed = _make_observations(payloads[::-1])

        profiler = PathStabilityProfiler()
        r_normal = profiler.profile(obs_normal)
        r_reversed = profiler.profile(obs_reversed)

        # Path volatilities and findings should be identical in structure
        # (same paths, same classifications) regardless of observation order.
        assert len(r_normal.path_volatilities) == len(r_reversed.path_volatilities)
        assert len(r_normal.findings) == len(r_reversed.findings)

        # The finding codes and paths must match
        normal_codes = [(f.code, f.path) for f in r_normal.findings]
        reversed_codes = [(f.code, f.path) for f in r_reversed.findings]
        assert normal_codes == reversed_codes


# ---------------------------------------------------------------------------
# Numeric drift detection
# ---------------------------------------------------------------------------


class TestNumericDrift:
    """Numeric values drifting across runs trigger INTEL_NUMERIC_DRIFT."""

    def test_integer_drift_detected(self):
        payloads = [json.dumps({"count": 100 + i}) for i in range(5)]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_NUMERIC_DRIFT in _finding_codes(result)

    def test_epoch_timestamp_detected_as_timestamp(self):
        """Epoch-like numbers within valid range -> INTEL_TIMESTAMP_PATTERN."""
        base = 1700000000
        payloads = [json.dumps({"ts": base + i * 60}) for i in range(5)]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        assert INTEL_TIMESTAMP_PATTERN in _finding_codes(result)


# ---------------------------------------------------------------------------
# Multiple paths and mixed classifications
# ---------------------------------------------------------------------------


class TestMixedClassifications:
    """Payloads with multiple paths of different volatility types."""

    def test_mixed_stable_and_volatile(self):
        payloads = [
            json.dumps({
                "stable_field": "constant",
                "volatile_field": f"value_{i}",
            })
            for i in range(5)
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        assert vol_map["$.stable_field"] == "stable"
        assert vol_map["$.volatile_field"] == "value_volatile"

    def test_nested_json_paths(self):
        payloads = [
            json.dumps({"data": {"id": str(uuid.uuid4()), "status": "ok"}})
            for _ in range(5)
        ]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        assert vol_map["$.data.id"] == "value_volatile"
        assert vol_map["$.data.status"] == "stable"


# ---------------------------------------------------------------------------
# Fix #1: Multiset semantics for list paths
# ---------------------------------------------------------------------------


class TestListPathMultiset:
    """Verify that generalized list paths preserve element multiplicity."""

    def test_duplicate_values_distinguishable(self):
        """[1,1,2] and [1,2,2] must produce different multisets."""
        p1 = json.dumps({"items": [1, 1, 2]})
        p2 = json.dumps({"items": [1, 2, 2]})
        obs = _make_observations([p1, p2, p1])
        result = PathStabilityProfiler(min_runs=1).profile(obs)

        vol_map = _volatility_map(result)
        # $.items[*] should be value_volatile (different multisets across runs)
        assert vol_map["$.items[*]"] == "value_volatile"

    def test_same_multiset_is_stable(self):
        """Same elements in same quantities → stable."""
        payload = json.dumps({"items": [1, 2, 1]})
        obs = _make_observations([payload] * 3)
        result = PathStabilityProfiler(min_runs=1).profile(obs)

        vol_map = _volatility_map(result)
        assert vol_map["$.items[*]"] == "stable"

    def test_mixed_types_under_generalized_path(self):
        """Mixed types in a list across runs → shape_volatile."""
        # Run 1: items has int+str mix → value_types = ("int", "str")
        # Run 2: items has only ints → value_types = ("int",)
        # Type-sets differ → shape_volatile
        p1 = json.dumps({"items": [1, "two", 3]})
        p2 = json.dumps({"items": [1, 2, 3]})
        obs = _make_observations([p1, p2, p1])
        result = PathStabilityProfiler(min_runs=1).profile(obs)

        vol_map = _volatility_map(result)
        assert vol_map["$.items[*]"] == "shape_volatile"


# ---------------------------------------------------------------------------
# Fix #2: Order volatile vs content volatile
# ---------------------------------------------------------------------------


class TestOrderVsContent:
    """order_volatile only when multiset is stable (same content, different order)."""

    def test_reorder_same_content_is_order_volatile(self):
        """Same elements, different order → order_volatile."""
        p1 = json.dumps({"items": [1, 2, 3]})
        p2 = json.dumps({"items": [3, 1, 2]})
        obs = _make_observations([p1, p2, p1, p2, p1])
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        assert vol_map.get("$.items[__order]") == "order_volatile"

    def test_content_change_not_order_volatile(self):
        """Different elements → NOT order_volatile (content changed)."""
        p1 = json.dumps({"items": [1, 2, 3]})
        p2 = json.dumps({"items": [4, 5, 6]})
        obs = _make_observations([p1, p2, p1, p2, p1])
        result = PathStabilityProfiler().profile(obs)

        vol_map = _volatility_map(result)
        # [__order] should NOT be order_volatile because content changed
        order_class = vol_map.get("$.items[__order]")
        assert order_class != "order_volatile"

    def test_content_path_not_in_output(self):
        """Internal [__content] paths must not appear in user-facing output."""
        payload = json.dumps({"items": [1, 2]})
        obs = _make_observations([payload] * 5)
        result = PathStabilityProfiler().profile(obs)

        paths = {v.path for v in result.path_volatilities}
        assert not any(p.endswith("[__content]") for p in paths)

        finding_paths = {f.path for f in result.findings}
        assert not any(p.endswith("[__content]") for p in finding_paths)


# ---------------------------------------------------------------------------
# Fix #4: total_runs parameter and missing run injection
# ---------------------------------------------------------------------------


class TestTotalRunsParameter:
    """Profiler respects explicit total_runs for conditional assert_match."""

    def test_conditional_assert_match_missing_runs(self):
        """3 observations across 5 total runs → paths are presence_volatile."""
        payloads = [json.dumps({"x": 1})] * 3
        obs = _make_observations(payloads)
        result = PathStabilityProfiler(min_runs=1).profile(obs, total_runs=5)

        vol_map = _volatility_map(result)
        # Path was present in 3/5 runs → presence_volatile
        assert vol_map["$.x"] == "presence_volatile"

    def test_default_total_runs_equals_observations(self):
        """Without explicit total_runs, defaults to len(observations)."""
        payloads = [json.dumps({"x": 1})] * 3
        obs = _make_observations(payloads)
        result = PathStabilityProfiler(min_runs=1).profile(obs)

        vol_map = _volatility_map(result)
        # 3/3 → stable
        assert vol_map["$.x"] == "stable"


# ===================================================================
# Boundary tests for _compute_confidence (TEST-4)
# ===================================================================


class TestConfidenceBoundary:
    """Edge cases for confidence scoring."""

    def test_single_run_confidence(self):
        """1 run → base = 0.2, stable returns 0.2."""
        payloads = [json.dumps({"x": 1})]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler(min_runs=1).profile(obs)
        for vol in result.path_volatilities:
            if vol.path == "$.x":
                assert vol.confidence == round(1 / 5, 4)

    def test_presence_volatile_single_present_entry(self):
        """presence_volatile with 1 present entry gets low-evidence penalty."""
        payloads = [json.dumps({"x": 1})]
        obs = _make_observations(payloads)
        # total_runs=3 but only 1 observation → presence_volatile
        profiler = PathStabilityProfiler(min_runs=1)
        result = profiler.profile(obs, total_runs=3)

        vol_map = _volatility_map(result)
        assert vol_map["$.x"] == "presence_volatile"
        for vol in result.path_volatilities:
            if vol.path == "$.x":
                # base = 3/5 = 0.6, penalty 0.5 → 0.3
                assert vol.confidence == round(3 / 5 * 0.5, 4)

    def test_confidence_capped_at_one(self):
        """10 runs → base = min(1.0, 10/5) = 1.0."""
        payloads = [json.dumps({"x": i}) for i in range(10)]
        obs = _make_observations(payloads)
        result = PathStabilityProfiler(min_runs=1).profile(obs)
        for vol in result.path_volatilities:
            if vol.path == "$.x":
                assert vol.confidence == 1.0
