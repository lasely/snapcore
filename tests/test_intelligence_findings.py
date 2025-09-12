"""Tests for intelligence finding builder functions."""

from __future__ import annotations

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
    build_insufficient_runs_finding,
    build_non_json_skipped_finding,
    build_numeric_drift_finding,
    build_order_volatile_finding,
    build_presence_volatile_finding,
    build_shape_volatile_finding,
    build_timestamp_pattern_finding,
    build_uuid_pattern_finding,
    build_value_volatile_finding,
)


class TestFindingBuilders:
    def test_value_volatile(self) -> None:
        f = build_value_volatile_finding(
            path="$.ts", total_runs=5, distinct_values=5,
            value_changes=4, confidence=0.95,
        )
        assert f.code == INTEL_VALUE_VOLATILE
        assert f.severity == "warning"
        assert f.path == "$.ts"
        assert f.volatility_class == "value_volatile"
        assert f.confidence == 0.95
        assert "4/4" in f.message
        assert len(f.evidence) == 2

    def test_presence_volatile(self) -> None:
        f = build_presence_volatile_finding(
            path="$.opt", total_runs=5, presence_count=3, confidence=0.8,
        )
        assert f.code == INTEL_PRESENCE_VOLATILE
        assert "3/5" in f.message

    def test_shape_volatile(self) -> None:
        f = build_shape_volatile_finding(
            path="$.val", total_runs=5, type_changes=2, confidence=0.7,
        )
        assert f.code == INTEL_SHAPE_VOLATILE
        assert "2" in f.message

    def test_order_volatile(self) -> None:
        f = build_order_volatile_finding(
            path="$.items", total_runs=5, order_changes=3, confidence=0.9,
        )
        assert f.code == INTEL_ORDER_VOLATILE
        assert "3/4" in f.message

    def test_timestamp_pattern(self) -> None:
        f = build_timestamp_pattern_finding(
            path="$.ts", total_runs=5, match_count=5, confidence=0.99,
        )
        assert f.code == INTEL_TIMESTAMP_PATTERN
        assert f.severity == "info"
        assert "5/5" in f.message

    def test_uuid_pattern(self) -> None:
        f = build_uuid_pattern_finding(
            path="$.id", total_runs=5, match_count=4, confidence=0.8,
        )
        assert f.code == INTEL_UUID_PATTERN
        assert "4/5" in f.message

    def test_numeric_drift(self) -> None:
        f = build_numeric_drift_finding(
            path="$.seq", total_runs=5, min_value=100, max_value=104,
            confidence=0.9,
        )
        assert f.code == INTEL_NUMERIC_DRIFT
        assert "100" in f.message
        assert "104" in f.message

    def test_non_json_skipped(self) -> None:
        f = build_non_json_skipped_finding(
            serializer_name="text",
            test_id="test_mod::test_fn",
            snapshot_name="0",
        )
        assert f.code == INTEL_NON_JSON_SKIPPED
        assert f.test_id == "test_mod::test_fn"
        assert "text" in f.message

    def test_insufficient_runs(self) -> None:
        f = build_insufficient_runs_finding(total_runs=2, min_runs=3)
        assert f.code == INTEL_INSUFFICIENT_RUNS
        assert f.severity == "warning"
        assert "2" in f.message
        assert f.confidence < 1.0
