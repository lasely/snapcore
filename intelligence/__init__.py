"""Flakiness intelligence engine for snapshot stability profiling.

This package implements cross-run analysis of snapshot targets to detect
path-level instability and emit actionable suggestions (sanitizer hints,
masking recommendations, relational sanitizer candidates).

Public API:

    Analyzer:
        ProfileAnalyzer -- single entry-point for plugin layer

    Collector:
        ObservationCollector -- session-scoped accumulator

    Models:
        ObservedPathValue, RunObservation, PathVolatility,
        InstabilityFinding, Suggestion, AnalysisReport

    Report:
        IntelligenceReport -- terminal + JSON rendering
"""

from .analyzer import ProfileAnalyzer
from .collector import ObservationCollector
from .models import (
    AnalysisReport,
    InstabilityFinding,
    ObservedPathValue,
    PathVolatility,
    RunObservation,
    Suggestion,
)
from .report import IntelligenceReport

__all__ = [
    "AnalysisReport",
    "InstabilityFinding",
    "IntelligenceReport",
    "ObservationCollector",
    "ObservedPathValue",
    "PathVolatility",
    "ProfileAnalyzer",
    "RunObservation",
    "Suggestion",
]
