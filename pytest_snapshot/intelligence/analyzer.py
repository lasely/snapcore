"""High-level analysis orchestrator for the intelligence engine.

``ProfileAnalyzer`` is the single entry-point that the plugin layer
calls after profiling runs complete.  It chains the profiler and
suggestion engine, and returns structured ``AnalysisReport`` objects.

This keeps the plugin layer (L4) free of business logic — it only
calls ``analyzer.analyze()`` and handles I/O (terminal output, sidecar).
"""

from __future__ import annotations

from .collector import ObservationCollector
from .models import AnalysisReport
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
        """Run profiler + suggestion engine on all collected observations.

        Returns one ``AnalysisReport`` per snapshot target, sorted by
        ``(module, class_name, test_name, snapshot_name)``.
        """
        reports: list[AnalysisReport] = []

        for key in sorted(
            collector.all_keys(),
            key=lambda k: (
                k.module, k.class_name or "", k.test_name, k.snapshot_name,
            ),
        ):
            observations = collector.observations_for(key)
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
