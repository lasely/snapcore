"""Comprehensive unit tests for pytest_snapshot.intelligence.extractor."""

from __future__ import annotations

import json

import pytest

from pytest_snapshot.intelligence.extractor import (
    compute_value_hash,
    extract_path_values,
)


# ===================================================================
# extract_path_values — flat dict
# ===================================================================


class TestExtractFlatDict:
    def test_flat_dict_paths(self):
        result = extract_path_values('{"name": "Alice", "age": 30}')
        paths = {r.path for r in result}
        assert "$.age" in paths
        assert "$.name" in paths

    def test_flat_dict_value_types(self):
        result = extract_path_values('{"name": "Alice", "age": 30}')
        by_path = {r.path: r for r in result}
        assert by_path["$.name"].value_type == "str"
        assert by_path["$.age"].value_type == "int"

    def test_flat_dict_value_repr(self):
        result = extract_path_values('{"name": "Alice"}')
        by_path = {r.path: r for r in result}
        assert by_path["$.name"].value_repr == '"Alice"'

    def test_flat_dict_is_present(self):
        result = extract_path_values('{"x": 1}')
        assert all(r.is_present for r in result)


# ===================================================================
# extract_path_values — nested dict
# ===================================================================


class TestExtractNestedDict:
    def test_nested_dict_dotted_paths(self):
        data = json.dumps({"user": {"profile": {"name": "Bob"}}})
        result = extract_path_values(data)
        paths = {r.path for r in result}
        assert "$.user.profile.name" in paths

    def test_nested_dict_multiple_leaves(self):
        data = json.dumps({"a": {"b": 1, "c": 2}})
        result = extract_path_values(data)
        paths = {r.path for r in result}
        assert "$.a.b" in paths
        assert "$.a.c" in paths


# ===================================================================
# extract_path_values — lists
# ===================================================================


class TestExtractLists:
    def test_list_concrete_indices_generalized(self):
        data = json.dumps({"items": ["x", "y"]})
        result = extract_path_values(data)
        scalar_paths = {r.path for r in result if r.value_type not in ("list_order", "list_content")}
        # Concrete indices [0], [1] should be generalized to [*]
        assert "$.items[*]" in scalar_paths

    def test_list_order_synthetic_path(self):
        data = json.dumps({"items": [1, 2, 3]})
        result = extract_path_values(data)
        order_entries = [r for r in result if r.value_type == "list_order"]
        assert len(order_entries) == 1
        assert order_entries[0].path == "$.items[__order]"

    def test_list_order_hash_deterministic(self):
        data = json.dumps({"items": [1, 2, 3]})
        r1 = extract_path_values(data)
        r2 = extract_path_values(data)
        order1 = [r for r in r1 if r.value_type == "list_order"][0]
        order2 = [r for r in r2 if r.value_type == "list_order"][0]
        assert order1.value_hash == order2.value_hash

    def test_list_order_differs_for_different_ordering(self):
        d1 = json.dumps({"items": [1, 2, 3]})
        d2 = json.dumps({"items": [3, 2, 1]})
        r1 = extract_path_values(d1)
        r2 = extract_path_values(d2)
        order1 = [r for r in r1 if r.value_type == "list_order"][0]
        order2 = [r for r in r2 if r.value_type == "list_order"][0]
        assert order1.value_hash != order2.value_hash

    def test_list_of_dicts(self):
        data = json.dumps({"users": [{"name": "A"}, {"name": "B"}]})
        result = extract_path_values(data)
        scalar_paths = {r.path for r in result if r.value_type not in ("list_order", "list_content")}
        assert "$.users[*].name" in scalar_paths

    def test_nested_list_multiple_order_entries(self):
        data = json.dumps({"a": [1], "b": [2]})
        result = extract_path_values(data)
        order_entries = [r for r in result if r.value_type == "list_order"]
        assert len(order_entries) == 2


# ===================================================================
# extract_path_values — edge cases
# ===================================================================


class TestExtractEdgeCases:
    def test_non_json_input_returns_empty(self):
        assert extract_path_values("not json at all") == []

    def test_empty_json_object_returns_empty(self):
        assert extract_path_values("{}") == []

    def test_empty_json_array_returns_order_and_content(self):
        result = extract_path_values("[]")
        # Empty array at root emits order + content synthetic entries
        assert len(result) == 2
        types = {r.value_type for r in result}
        assert types == {"list_order", "list_content"}

    def test_max_depth_truncation(self):
        # Build deeply nested structure
        data: dict = {"a": {"b": {"c": {"d": "deep"}}}}
        # max_depth=2 should only go two levels: $ -> $.a -> $.a.b (stop)
        result = extract_path_values(json.dumps(data), max_depth=2)
        paths = {r.path for r in result}
        assert "$.a.b.c.d" not in paths

    def test_null_value(self):
        data = json.dumps({"x": None})
        result = extract_path_values(data)
        by_path = {r.path: r for r in result}
        assert by_path["$.x"].value_type == "null"
        assert by_path["$.x"].value_repr == "null"

    def test_bool_vs_int_type_distinction(self):
        data = json.dumps({"flag": True, "count": 1})
        result = extract_path_values(data)
        by_path = {r.path: r for r in result}
        assert by_path["$.flag"].value_type == "bool"
        assert by_path["$.count"].value_type == "int"

    def test_float_type(self):
        data = json.dumps({"price": 9.99})
        result = extract_path_values(data)
        by_path = {r.path: r for r in result}
        assert by_path["$.price"].value_type == "float"

    def test_none_input_returns_empty(self):
        # json.loads(None) raises TypeError, should be caught
        assert extract_path_values(None) == []  # type: ignore[arg-type]


# ===================================================================
# compute_value_hash
# ===================================================================


class TestComputeValueHash:
    def test_deterministic_same_input(self):
        h1 = compute_value_hash("hello")
        h2 = compute_value_hash("hello")
        assert h1 == h2

    def test_different_strings_differ(self):
        assert compute_value_hash("abc") != compute_value_hash("xyz")

    def test_bool_vs_int_distinction(self):
        # True and 1 must produce different hashes
        assert compute_value_hash(True) != compute_value_hash(1)

    def test_int_vs_float_distinction(self):
        # 1 and 1.0 must produce different hashes
        assert compute_value_hash(1) != compute_value_hash(1.0)

    def test_string_hashing(self):
        h = compute_value_hash("snapshot")
        assert isinstance(h, str)
        assert len(h) == 16  # sha256 hex truncated to 16

    def test_null_hash(self):
        h = compute_value_hash(None)
        assert isinstance(h, str)
        assert len(h) == 16

    def test_false_vs_zero(self):
        assert compute_value_hash(False) != compute_value_hash(0)

    def test_empty_string(self):
        h = compute_value_hash("")
        assert isinstance(h, str)
        assert len(h) == 16


# ===================================================================
# Contract tests: alignment module compatibility (TEST-3)
# ===================================================================

class TestAlignmentContract:
    """Verify extractor uses generalize_indices consistently with alignment module."""

    def test_generalize_indices_format(self):
        """Extractor paths use [*] for list indices, matching alignment module."""
        from pytest_snapshot.alignment.paths import generalize_indices
        assert generalize_indices("$.items[0].name") == "$.items[*].name"
        assert generalize_indices("$.a[0][1].b") == "$.a[*][*].b"

    def test_extracted_paths_match_alignment_format(self):
        """Paths emitted by extract_path_values use alignment's generalized format."""
        from pytest_snapshot.alignment.paths import generalize_indices

        data = json.dumps({"items": [{"name": "a"}, {"name": "b"}]})
        pvs = extract_path_values(data)
        scalar_paths = [pv.path for pv in pvs if not pv.path.endswith("]")]
        for path in scalar_paths:
            assert path == generalize_indices(path), (
                f"Path {path!r} not in generalized form"
            )
