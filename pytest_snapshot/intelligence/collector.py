"""Session-scoped observation collector for profile mode.

The collector accumulates ``RunObservation`` records across multiple
profile-mode iterations within a single pytest session.  It is stored
in the pytest config stash and injected into ``SnapshotAssertion`` via
the ``snapshot`` fixture.

Observations are kept in memory only — no persistence between pytest
invocations.  The only persistent output is the final JSON report sidecar
written by ``IntelligenceReport`` after all runs complete.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import SnapshotKey
from .extractor import extract_path_values
from .models import RunObservation


class ObservationCollector:
    """Accumulate run observations across profile-mode iterations.

    Lifecycle:

    1. Created in ``pytest_configure`` when ``--snapshot-profile`` is active.
    2. ``start_run()`` called at the beginning of each profile iteration.
    3. ``record()`` called from ``facade.assert_match()`` after ``runtime.prepare()``.
    4. After all iterations, ``pytest_sessionfinish`` reads observations and
       passes them to the profiler.

    Thread safety is not required (pytest is single-threaded per worker,
    and profile mode is mutually exclusive with xdist).
    """

    def __init__(self) -> None:
        self._observations: dict[SnapshotKey, list[RunObservation]] = {}
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
        """Record one observation for the current run.

        Extracts path-value pairs from the serialized text (post-sanitization)
        and stores them as a ``RunObservation``.  If ``json.loads`` fails
        (non-JSON serializer), path_values will be an empty tuple.

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

        path_values = extract_path_values(serialized_text)
        observation = RunObservation(
            key=key,
            run_index=self._current_run_index,
            serializer_name=serializer_name,
            path_values=tuple(path_values),
            raw_text=serialized_text,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if key not in self._observations:
            self._observations[key] = []
        self._observations[key].append(observation)

    def observations_for(self, key: SnapshotKey) -> list[RunObservation]:
        """Return all observations for a given snapshot target."""
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
