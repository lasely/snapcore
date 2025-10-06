"""Comprehensive unit tests for SuggestionEngine.

Tests cover pattern-based suggestions (timestamp, UUID), mask-based fallback,
relational sanitizer detection, confidence filtering, canonical sort order,
and edge cases.
"""

from __future__ import annotations

import json
import uuid

import pytest

from pytest_snapshot.intelligence.analyzer import ProfileAnalyzer
from pytest_snapshot.intelligence.collector import ObservationCollector
from pytest_snapshot.intelligence.findings import (
    INTEL_TIMESTAMP_PATTERN,
    INTEL_UUID_PATTERN,
    INTEL_VALUE_VOLATILE,
)
from pytest_snapshot.intelligence.profiler import PathStabilityProfiler
from pytest_snapshot.intelligence.suggestions import (
    SUGGEST_JSON_MASK,
    SUGGEST_RELATIONAL_SANITIZER,
    SUGGEST_SANITIZER,
    SuggestionEngine,
)
from pytest_snapshot.intelligence.models import AnalysisReport, Suggestion
from pytest_snapshot.intelligence.report import IntelligenceReport
from pytest_snapshot.models import SnapshotKey


_DEFAULT_KEY = SnapshotKey(
    module="test_mod", class_name=None, test_name="test_fn", snapshot_name="0"
)


def _make_observations(
    payloads: list[str],
    serializer_name: str = "json",
) -> list:
    """Build RunObservation list from serialized payloads."""
    collector = ObservationCollector()
    for payload in payloads:
        collector.start_run()
        collector.record(_DEFAULT_KEY, payload, serializer_name)
    return [
        ProfileAnalyzer._extract(raw)
        for raw in collector.observations_for(_DEFAULT_KEY)
    ]


def _profile_and_suggest(payloads: list[str], *, min_runs: int = 2):
    """Run profiler then suggestion engine; return (ProfileResult, suggestions)."""
    obs = _make_observations(payloads)
    profiler = PathStabilityProfiler(min_runs=min_runs)
    result = profiler.profile(obs)
    engine = SuggestionEngine()
    suggestions = engine.analyze(
        list(result.findings),
        list(result.path_volatilities),
        obs,
    )
    return result, suggestions


def _suggestion_codes(suggestions) -> list[str]:
    """Extract suggestion codes."""
    return [s.code for s in suggestions]


def _suggestion_params(suggestion) -> dict[str, str]:
    """Extract parameters as a dict from a Suggestion."""
    if suggestion.parameters is None:
        return {}
    return dict(suggestion.parameters)


class TestTimestampSuggestion:
    """Timestamp-volatile path should produce a sanitizer suggestion."""

    def test_timestamp_suggests_sanitizer(self):
        payloads = [
            json.dumps({"created_at": f"2024-01-{10 + i}T12:00:00Z"})
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        assert SUGGEST_SANITIZER in _suggestion_codes(suggestions)

    def test_timestamp_sanitizer_type_datetime(self):
        payloads = [
            json.dumps({"created_at": f"2024-01-{10 + i}T12:00:00Z"})
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        sanitizer_suggestions = [s for s in suggestions if s.code == SUGGEST_SANITIZER]
        assert len(sanitizer_suggestions) >= 1
        params = _suggestion_params(sanitizer_suggestions[0])
        assert params.get("sanitizer_type") == "datetime"

    def test_timestamp_suggestion_targets_correct_path(self):
        payloads = [
            json.dumps({"meta": {"ts": f"2024-06-{10 + i}T08:00:00Z"}})
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        sanitizer_suggestions = [s for s in suggestions if s.code == SUGGEST_SANITIZER]
        assert any(s.target_path == "$.meta.ts" for s in sanitizer_suggestions)

    def test_timestamp_evidence_includes_both_codes(self):
        payloads = [
            json.dumps({"ts": f"2024-01-{10 + i}T12:00:00Z"})
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        sanitizer_suggestions = [s for s in suggestions if s.code == SUGGEST_SANITIZER]
        assert len(sanitizer_suggestions) >= 1
        evidence = sanitizer_suggestions[0].evidence_findings
        assert INTEL_TIMESTAMP_PATTERN in evidence
        assert INTEL_VALUE_VOLATILE in evidence


class TestUuidSuggestion:
    """UUID-volatile path should produce a sanitizer suggestion."""

    def test_uuid_suggests_sanitizer(self):
        payloads = [
            json.dumps({"request_id": str(uuid.uuid4())}) for _ in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        assert SUGGEST_SANITIZER in _suggestion_codes(suggestions)

    def test_uuid_sanitizer_type_uuid(self):
        payloads = [
            json.dumps({"request_id": str(uuid.uuid4())}) for _ in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        sanitizer_suggestions = [s for s in suggestions if s.code == SUGGEST_SANITIZER]
        assert len(sanitizer_suggestions) >= 1
        params = _suggestion_params(sanitizer_suggestions[0])
        assert params.get("sanitizer_type") == "uuid"

    def test_uuid_suggestion_targets_correct_path(self):
        payloads = [
            json.dumps({"id": str(uuid.uuid4())}) for _ in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        sanitizer_suggestions = [s for s in suggestions if s.code == SUGGEST_SANITIZER]
        assert any(s.target_path == "$.id" for s in sanitizer_suggestions)

    def test_uuid_evidence_includes_both_codes(self):
        payloads = [
            json.dumps({"id": str(uuid.uuid4())}) for _ in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        sanitizer_suggestions = [
            s for s in suggestions
            if s.code == SUGGEST_SANITIZER and s.target_path == "$.id"
        ]
        assert len(sanitizer_suggestions) >= 1
        evidence = sanitizer_suggestions[0].evidence_findings
        assert INTEL_UUID_PATTERN in evidence
        assert INTEL_VALUE_VOLATILE in evidence


class TestJsonMaskSuggestion:
    """Value-volatile without recognized pattern -> JSON mask suggestion."""

    def test_generic_volatile_suggests_json_mask(self):
        payloads = [
            json.dumps({"random_str": f"xyzzy_{i}_abc"}) for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        assert SUGGEST_JSON_MASK in _suggestion_codes(suggestions)

    def test_json_mask_target_path(self):
        payloads = [
            json.dumps({"nonce": f"random_{i}"}) for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        mask_suggestions = [s for s in suggestions if s.code == SUGGEST_JSON_MASK]
        assert any(s.target_path == "$.nonce" for s in mask_suggestions)

    def test_json_mask_has_mask_value_param(self):
        payloads = [
            json.dumps({"nonce": f"random_{i}"}) for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        mask_suggestions = [s for s in suggestions if s.code == SUGGEST_JSON_MASK]
        assert len(mask_suggestions) >= 1
        params = _suggestion_params(mask_suggestions[0])
        assert "mask_value" in params

    def test_json_mask_confidence_penalized(self):
        """Mask suggestions get a 0.9x confidence penalty vs raw finding."""
        payloads = [
            json.dumps({"nonce": f"random_{i}"}) for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        mask_suggestions = [s for s in suggestions if s.code == SUGGEST_JSON_MASK]
        assert len(mask_suggestions) >= 1
        assert mask_suggestions[0].confidence == pytest.approx(0.9, abs=0.01)

    def test_json_mask_evidence_contains_value_volatile(self):
        payloads = [
            json.dumps({"nonce": f"random_{i}"}) for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        mask_suggestions = [s for s in suggestions if s.code == SUGGEST_JSON_MASK]
        assert len(mask_suggestions) >= 1
        assert INTEL_VALUE_VOLATILE in mask_suggestions[0].evidence_findings


class TestRelationalSanitizer:
    """Multiple volatile siblings under same parent -> relational suggestion."""

    def test_correlated_siblings_suggest_relational(self):
        payloads = [
            json.dumps({
                "user": {
                    "first_name": f"name_{i}",
                    "last_name": f"surname_{i}",
                    "age": 30,
                }
            })
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        assert SUGGEST_RELATIONAL_SANITIZER in _suggestion_codes(suggestions)

    def test_relational_suggestion_targets_parent_path(self):
        payloads = [
            json.dumps({
                "user": {
                    "first_name": f"name_{i}",
                    "last_name": f"surname_{i}",
                    "age": 30,
                }
            })
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        rel_suggestions = [
            s for s in suggestions if s.code == SUGGEST_RELATIONAL_SANITIZER
        ]
        assert any(s.target_path == "$.user" for s in rel_suggestions)

    def test_relational_has_volatile_field_params(self):
        payloads = [
            json.dumps({
                "user": {
                    "field_a": f"a_{i}",
                    "field_b": f"b_{i}",
                    "stable": "ok",
                }
            })
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        rel_suggestions = [
            s for s in suggestions if s.code == SUGGEST_RELATIONAL_SANITIZER
        ]
        assert len(rel_suggestions) >= 1
        params = rel_suggestions[0].parameters
        assert params is not None
        volatile_fields = [v for k, v in params if k == "volatile_field"]
        assert "$.user.field_a" in volatile_fields
        assert "$.user.field_b" in volatile_fields

    def test_relational_confidence_penalized(self):
        """Relational suggestions get a 0.85x confidence penalty."""
        payloads = [
            json.dumps({
                "obj": {"a": f"a_{i}", "b": f"b_{i}", "c": "stable"}
            })
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        rel_suggestions = [
            s for s in suggestions if s.code == SUGGEST_RELATIONAL_SANITIZER
        ]
        assert len(rel_suggestions) >= 1
        assert rel_suggestions[0].confidence == pytest.approx(0.85, abs=0.01)

    def test_relational_evidence_contains_value_volatile(self):
        payloads = [
            json.dumps({
                "obj": {"a": f"a_{i}", "b": f"b_{i}", "c": "stable"}
            })
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        rel_suggestions = [
            s for s in suggestions if s.code == SUGGEST_RELATIONAL_SANITIZER
        ]
        assert len(rel_suggestions) >= 1
        assert INTEL_VALUE_VOLATILE in rel_suggestions[0].evidence_findings


class TestStableNoSuggestions:
    """Fully stable payload should produce no suggestions."""

    def test_stable_payload_no_suggestions(self):
        payloads = [json.dumps({"name": "Alice", "age": 30})] * 5
        _, suggestions = _profile_and_suggest(payloads)

        assert suggestions == []


class TestEmptyFindings:
    """No findings at all -> no suggestions."""

    def test_empty_observations_no_suggestions(self):
        engine = SuggestionEngine()
        suggestions = engine.analyze([], [], [])

        assert suggestions == []

    def test_non_json_no_suggestions(self):
        """Non-JSON observations produce only INTEL_NON_JSON_SKIPPED, no suggestions."""
        obs = _make_observations(["not json"] * 5, serializer_name="repr")
        profiler = PathStabilityProfiler()
        result = profiler.profile(obs)
        engine = SuggestionEngine()
        suggestions = engine.analyze(
            list(result.findings),
            list(result.path_volatilities),
            obs,
        )
        assert suggestions == []


class TestConfidenceFiltering:
    """Suggestions with confidence < 0.3 are excluded."""

    def test_all_returned_suggestions_above_threshold(self):
        payloads = [json.dumps({"x": f"val_{i}"}) for i in range(5)]
        _, suggestions = _profile_and_suggest(payloads)

        assert all(s.confidence >= 0.3 for s in suggestions)

    def test_sufficient_runs_high_confidence_kept(self):
        payloads = [json.dumps({"x": f"val_{i}"}) for i in range(5)]
        _, suggestions = _profile_and_suggest(payloads)

        assert len(suggestions) > 0

    def test_two_runs_volatile_passes_threshold(self):
        """2 runs -> confidence = 0.4 * 0.9 (mask penalty) = 0.36 >= 0.3."""
        payloads = [json.dumps({"x": f"val_{i}"}) for i in range(2)]
        _, suggestions = _profile_and_suggest(payloads, min_runs=1)

        assert all(s.confidence >= 0.3 for s in suggestions)


class TestCanonicalSortOrder:
    """Suggestions must be sorted by (confidence DESC, target_path ASC, code ASC)."""

    def test_suggestions_sorted_correctly(self):
        payloads = [
            json.dumps({
                "ts": f"2024-01-{10 + i}T00:00:00Z",
                "nonce": f"random_{i}",
                "uuid_field": str(uuid.uuid4()),
            })
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        prev = None
        for s in suggestions:
            key = (-s.confidence, s.target_path, s.code)
            if prev is not None:
                assert key >= prev, (
                    f"Suggestions not in canonical order: {prev} > {key}"
                )
            prev = key

    def test_multiple_paths_sorted_by_path_within_confidence(self):
        """Paths with equal confidence sorted alphabetically."""
        payloads = [
            json.dumps({
                "z_field": f"val_{i}",
                "a_field": f"val_{i}",
            })
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        by_conf: dict[float, list] = {}
        for s in suggestions:
            by_conf.setdefault(s.confidence, []).append(s)
        for conf, group in by_conf.items():
            paths = [s.target_path for s in group]
            assert paths == sorted(paths), (
                f"Paths not sorted within confidence {conf}: {paths}"
            )


class TestPatternPriority:
    """Pattern-based suggestion takes priority over mask for the same path."""

    def test_timestamp_path_gets_sanitizer_not_mask(self):
        payloads = [
            json.dumps({"ts": f"2024-01-{10 + i}T12:00:00Z"})
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        ts_suggestions = [s for s in suggestions if s.target_path == "$.ts"]
        codes = [s.code for s in ts_suggestions]
        assert SUGGEST_SANITIZER in codes
        assert SUGGEST_JSON_MASK not in codes

    def test_uuid_path_gets_sanitizer_not_mask(self):
        payloads = [
            json.dumps({"id": str(uuid.uuid4())}) for _ in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        id_suggestions = [s for s in suggestions if s.target_path == "$.id"]
        codes = [s.code for s in id_suggestions]
        assert SUGGEST_SANITIZER in codes
        assert SUGGEST_JSON_MASK not in codes

    def test_pattern_handled_path_excluded_from_relational(self):
        """Paths handled by pattern-based suggestions should not appear in relational."""
        payloads = [
            json.dumps({
                "data": {
                    "ts": f"2024-01-{10 + i}T12:00:00Z",
                    "id": str(uuid.uuid4()),
                    "stable": "ok",
                }
            })
            for i in range(5)
        ]
        _, suggestions = _profile_and_suggest(payloads)

        rel_suggestions = [
            s for s in suggestions if s.code == SUGGEST_RELATIONAL_SANITIZER
        ]
        assert len(rel_suggestions) == 0


class TestRelationalParametersSerialization:
    """Verify all volatile_field params survive JSON serialization."""

    def test_all_volatile_fields_preserved_in_sidecar(self):
        """Multiple volatile_field entries must not collapse to one in JSON."""
        key = SnapshotKey(
            module="test_mod", class_name=None,
            test_name="test_fn", snapshot_name="0",
        )
        suggestion = Suggestion(
            code=SUGGEST_RELATIONAL_SANITIZER,
            message="Consider relational sanitizer for $.data",
            action_type="relational_sanitize",
            target_path="$.data",
            confidence=0.5,
            evidence_findings=(INTEL_VALUE_VOLATILE,),
            parameters=(
                ("volatile_field", "$.data.x"),
                ("volatile_field", "$.data.y"),
                ("volatile_field", "$.data.z"),
            ),
        )
        report = AnalysisReport(
            key=key, total_runs=5,
            path_volatilities=(), findings=(),
            suggestions=(suggestion,),
            summary=(("total_paths", "3"),),
        )
        intel_report = IntelligenceReport([report])
        data = json.loads(intel_report.render_json())

        params = data["targets"][0]["suggestions"][0]["parameters"]
        assert "volatile_field" in params
        assert isinstance(params["volatile_field"], list)
        assert len(params["volatile_field"]) == 3
        assert set(params["volatile_field"]) == {"$.data.x", "$.data.y", "$.data.z"}
