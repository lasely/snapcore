"""High-level analysis orchestrator for the intelligence engine.

``ProfileAnalyzer`` is the single entry-point that the plugin layer
calls after profiling runs complete.  It converts raw observations into
``RunObservation`` records (with path extraction), then chains the
profiler and suggestion engine to produce ``AnalysisReport`` objects.

This keeps the plugin layer (L4) free of business logic — it only
calls ``analyzer.analyze()`` and handles I/O (terminal output, sidecar).
"""

from __future__ import annotations

from .collector import ObservationCollector, RawObservation
from .extractor import extract_path_values
from .models import AnalysisReport, RunObservation
from .profiler import PathStabilityProfiler
from .suggestions import SuggestionEngine


class ProfileAnalyzer:
    """Orchestrate the intelligence analysis pipeline.

    Usage::

        analyzer = ProfileAnalyzer(min_runs=3)
        reports = analyzer.analyze(collector)
    """

    def __init__(self, *, min_runs: int = 3) -> None:
        self._profiler = PathStabilityProfiler(min_runs=min_runs)
        self._engine = SuggestionEngine()

    def analyze(
        self, collector: ObservationCollector,
    ) -> list[AnalysisReport]:
        """Run extraction + profiler + suggestion engine.

        Converts raw observations to ``RunObservation`` (with path
        extraction), then profiles and generates suggestions.  Returns
        one ``AnalysisReport`` per snapshot target, sorted by
        ``(module, class_name, test_name, snapshot_name)``.
        """
        reports: list[AnalysisReport] = []

        for key in sorted(
            collector.all_keys(),
            key=lambda k: (
                k.module, k.class_name or "", k.test_name, k.snapshot_name,
            ),
        ):
            raw_observations = collector.observations_for(key)
            observations = [
                self._extract(raw) for raw in raw_observations
            ]

            result = self._profiler.profile(
                observations, total_runs=collector.run_count,
            )
            suggestions = self._engine.analyze(
                list(result.findings),
                list(result.path_volatilities),
                observations,
            )

            volatile_count = sum(
                1 for v in result.path_volatilities
                if v.volatility_class != "stable"
            )
            stable_count = sum(
                1 for v in result.path_volatilities
                if v.volatility_class == "stable"
            )
            total_count = len(result.path_volatilities)

            reports.append(AnalysisReport(
                key=key,
                total_runs=collector.run_count,
                path_volatilities=result.path_volatilities,
                findings=result.findings,
                suggestions=tuple(suggestions),
                summary=(
                    ("total_paths", str(total_count)),
                    ("stable_paths", str(stable_count)),
                    ("volatile_paths", str(volatile_count)),
                    ("suggestions_count", str(len(suggestions))),
                ),
            ))

        return reports

    @staticmethod
    def _extract(raw: RawObservation) -> RunObservation:
        """Convert a raw observation to a RunObservation with path extraction."""
        path_values = extract_path_values(raw.serialized_text)
        return RunObservation(
            key=raw.key,
            run_index=raw.run_index,
            serializer_name=raw.serializer_name,
            path_values=tuple(path_values),
            raw_text=raw.serialized_text,
            timestamp=raw.timestamp,
        )
