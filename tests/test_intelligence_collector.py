"""Tests for intelligence observation collector."""

from __future__ import annotations

import json

import pytest

from pytest_snapshot.intelligence.collector import ObservationCollector
from pytest_snapshot.models import SnapshotKey


def _key(name: str = "0", test: str = "test_fn") -> SnapshotKey:
    return SnapshotKey(module="test_mod", class_name=None, test_name=test, snapshot_name=name)


class TestObservationCollector:
    def test_initial_state(self) -> None:
        c = ObservationCollector()
        assert c.run_count == 0
        assert c.total_observations == 0
        assert c.all_keys() == set()

    def test_start_run_increments(self) -> None:
        c = ObservationCollector()
        c.start_run()
        assert c.run_count == 1
        c.start_run()
        assert c.run_count == 2

    def test_record_before_start_run_raises(self) -> None:
        c = ObservationCollector()
        with pytest.raises(RuntimeError, match="before start_run"):
            c.record(_key(), '{"a": 1}', "json")

    def test_record_stores_observation(self) -> None:
        c = ObservationCollector()
        key = _key()
        c.start_run()
        c.record(key, '{"x": 1}', "json")
        obs = c.observations_for(key)
        assert len(obs) == 1
        assert obs[0].key == key
        assert obs[0].run_index == 0
        assert obs[0].serializer_name == "json"
        assert obs[0].serialized_text == '{"x": 1}'

    def test_record_stores_raw_text_without_extraction(self) -> None:
        """Collector is a pure accumulator -- no path extraction in record()."""
        c = ObservationCollector()
        key = _key()
        c.start_run()
        c.record(key, json.dumps({"a": 1, "b": "hello"}), "json")
        obs = c.observations_for(key)
        assert len(obs) == 1
        assert not hasattr(obs[0], "path_values")
        assert obs[0].serialized_text == json.dumps({"a": 1, "b": "hello"})

    def test_record_non_json_stores_text(self) -> None:
        c = ObservationCollector()
        key = _key()
        c.start_run()
        c.record(key, "plain text", "text")
        obs = c.observations_for(key)
        assert obs[0].serialized_text == "plain text"

    def test_multiple_runs_same_key(self) -> None:
        c = ObservationCollector()
        key = _key()
        for i in range(3):
            c.start_run()
            c.record(key, json.dumps({"v": i}), "json")
        obs = c.observations_for(key)
        assert len(obs) == 3
        assert [o.run_index for o in obs] == [0, 1, 2]

    def test_multiple_keys(self) -> None:
        c = ObservationCollector()
        k1 = _key("0", "test_a")
        k2 = _key("0", "test_b")
        c.start_run()
        c.record(k1, '{"a": 1}', "json")
        c.record(k2, '{"b": 2}', "json")
        assert c.all_keys() == {k1, k2}
        assert len(c.observations_for(k1)) == 1
        assert len(c.observations_for(k2)) == 1

    def test_observations_for_unknown_key_returns_empty(self) -> None:
        c = ObservationCollector()
        assert c.observations_for(_key("unknown")) == []

    def test_observations_for_returns_copy(self) -> None:
        c = ObservationCollector()
        key = _key()
        c.start_run()
        c.record(key, '{"a": 1}', "json")
        obs1 = c.observations_for(key)
        obs2 = c.observations_for(key)
        assert obs1 == obs2
        assert obs1 is not obs2

    def test_total_observations(self) -> None:
        c = ObservationCollector()
        k1 = _key("0", "test_a")
        k2 = _key("0", "test_b")
        c.start_run()
        c.record(k1, '{"a": 1}', "json")
        c.record(k2, '{"b": 2}', "json")
        c.start_run()
        c.record(k1, '{"a": 2}', "json")
        assert c.total_observations == 3
