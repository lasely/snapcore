"""Flakiness intelligence engine for snapshot stability profiling.

This package implements cross-run analysis of snapshot targets to detect
path-level instability and emit actionable suggestions (sanitizer hints,
masking recommendations, relational sanitizer candidates).

The profiler operates on serialized+sanitized text (the same content that
would be stored in snapshot files), not raw Python values.  This ensures
suggestions are relevant to the actual snapshot pipeline configuration.

Public API:

    Models (INTEL-001):
        ObservedPathValue, RunObservation, PathVolatility,
        InstabilityFinding, Suggestion, AnalysisReport

    Collector (INTEL-002):
        ObservationCollector

    Profiler (INTEL-003):
        PathStabilityProfiler, ProfileResult

    Suggestions (INTEL-004):
        SuggestionEngine

    Report:
        IntelligenceReport
"""

from .models import (
    AnalysisReport,
    InstabilityFinding,
    ObservedPathValue,
    PathVolatility,
    RunObservation,
    Suggestion,
)

__all__ = [
    "AnalysisReport",
    "InstabilityFinding",
    "ObservedPathValue",
    "PathVolatility",
    "RunObservation",
    "Suggestion",
]
