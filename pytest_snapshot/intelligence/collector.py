"""Session-scoped observation collector for profile mode.

The collector is a pure accumulator: it stores raw serialized text
and metadata, deferring path extraction to the analysis phase
(``ProfileAnalyzer``).  This keeps the hot path (test execution)
lightweight and separates collection from transformation.

Observations are kept in memory only — no persistence between pytest
invocations.  The only persistent output is the final JSON report sidecar
written by ``IntelligenceReport`` after all runs complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import SnapshotKey


@dataclass(frozen=True, slots=True)
class RawObservation:
    """Raw observation stored during test execution.

    Lightweight record — no path extraction, no hashing.
    Path extraction is deferred to ``ProfileAnalyzer.analyze()``.
    """

    key: SnapshotKey
    run_index: int
    serializer_name: str
    serialized_text: str
    timestamp: str


class ObservationCollector:
    """Accumulate raw observations across profile-mode iterations.

    Lifecycle:

    1. Created in ``pytest_configure`` when ``--snapshot-profile`` is active.
    2. ``start_run()`` called at the beginning of each profile iteration.
    3. ``record()`` called from ``facade.assert_match()`` after ``runtime.prepare()``.
    4. After all iterations, ``ProfileAnalyzer`` reads raw observations,
       runs extraction, and passes results to the profiler.

    Thread safety is not required (pytest is single-threaded per worker,
    and profile mode is mutually exclusive with xdist).
    """

    def __init__(self) -> None:
        self._observations: dict[SnapshotKey, list[RawObservation]] = {}
        self._current_run_index: int = -1

    def start_run(self) -> None:
        """Increment the run index at the start of each profile iteration."""
        self._current_run_index += 1

    def record(
        self,
        key: SnapshotKey,
        serialized_text: str,
        serializer_name: str,
    ) -> None:
        """Record one raw observation for the current run.

        Parameters
        ----------
        key:
            Identifies the snapshot target.
        serialized_text:
            ``PreparedAssertion.actual`` — the serialized and sanitized text.
        serializer_name:
            Name of the serializer that produced the text.
        """
        if self._current_run_index < 0:
            raise RuntimeError(
                "ObservationCollector.record() called before start_run()"
            )

        observation = RawObservation(
            key=key,
            run_index=self._current_run_index,
            serializer_name=serializer_name,
            serialized_text=serialized_text,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if key not in self._observations:
            self._observations[key] = []
        self._observations[key].append(observation)

    def observations_for(self, key: SnapshotKey) -> list[RawObservation]:
        """Return all raw observations for a given snapshot target."""
        return list(self._observations.get(key, []))

    def all_keys(self) -> set[SnapshotKey]:
        """Return the set of all observed snapshot keys."""
        return set(self._observations.keys())

    @property
    def run_count(self) -> int:
        """Return the number of completed profile runs (0-indexed internally)."""
        return self._current_run_index + 1

    @property
    def total_observations(self) -> int:
        """Return the total number of recorded observations across all keys."""
        return sum(len(obs) for obs in self._observations.values())
