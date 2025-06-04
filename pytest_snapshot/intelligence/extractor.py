"""Path extraction from serialized JSON for stability profiling.

The extractor parses serialized+sanitized JSON text and walks the resulting
structure to emit ``ObservedPathValue`` records for every leaf-level path.
Paths are generalized (concrete indices replaced with ``[*]``) so that
cross-run aggregation works even when list lengths differ between runs.

The extractor reuses ``alignment.paths.generalize_indices`` for path
generalization, keeping behavior consistent between the alignment engine
and the intelligence profiler.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..alignment.paths import generalize_indices
from .models import ObservedPathValue

_MAX_REPR_LENGTH = 120


def extract_path_values(
    serialized_text: str,
    *,
    max_depth: int = 20,
) -> list[ObservedPathValue]:
    """Extract leaf-level path-value pairs from serialized JSON text.

    Parses the text via ``json.loads`` and recursively walks the resulting
    structure.  Each leaf scalar produces one ``ObservedPathValue`` with a
    generalized path (``$.users[*].name`` rather than ``$.users[0].name``).

    For list nodes, an additional synthetic entry is emitted to capture
    the *order* of child elements (used for order-volatility detection).

    Returns an empty list if ``json.loads`` fails (non-JSON serializer).

    Parameters
    ----------
    serialized_text:
        The post-serialization, post-sanitization snapshot text.
    max_depth:
        Maximum recursion depth to prevent stack overflow on
        pathological inputs.  Paths deeper than this are silently
        truncated.
    """
    try:
        obj = json.loads(serialized_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

    results: list[ObservedPathValue] = []
    _walk(obj, "$", results, max_depth, 0)
    return results


def _walk(
    obj: Any,
    path: str,
    results: list[ObservedPathValue],
    max_depth: int,
    depth: int,
) -> None:
    """Recursively walk a JSON-compatible object and emit path-value pairs."""
    if depth >= max_depth:
        return

    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            child_path = f"{path}.{key}"
            _walk(obj[key], child_path, results, max_depth, depth + 1)
    elif isinstance(obj, list):
        # Emit per-element entries with concrete indices
        for i, elem in enumerate(obj):
            child_path = f"{path}[{i}]"
            _walk(elem, child_path, results, max_depth, depth + 1)
        # Emit a synthetic entry for the list itself to capture ordering
        gen_path = generalize_indices(path)
        order_hash = _compute_list_order_hash(obj)
        results.append(ObservedPathValue(
            path=f"{gen_path}.__order__",
            value_hash=order_hash,
            value_type="list_order",
            value_repr=f"[...{len(obj)} items]",
            is_present=True,
        ))
    else:
        # Scalar value — generalize indices in the path
        gen_path = generalize_indices(path)
        results.append(ObservedPathValue(
            path=gen_path,
            value_hash=compute_value_hash(obj),
            value_type=type(obj).__name__ if obj is not None else "null",
            value_repr=_truncate_repr(obj),
            is_present=True,
        ))


def compute_value_hash(value: Any) -> str:
    """Compute a deterministic hash for a JSON-compatible scalar value.

    Uses SHA-256 of a canonical string representation.  The representation
    distinguishes types: ``True`` (bool) and ``1`` (int) produce different
    hashes.

    For unhashable or unexpected values, falls back to ``repr()``-based
    hashing to avoid raising exceptions during profiling.
    """
    canonical = _canonical_repr(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _canonical_repr(value: Any) -> str:
    """Produce a type-tagged canonical string for hashing.

    Type tagging ensures that ``True`` and ``1``, or ``1`` and ``1.0``,
    produce different hashes (matching Python's strict type semantics
    used elsewhere in the project).
    """
    if value is None:
        return "null:"
    if isinstance(value, bool):
        return f"bool:{'true' if value else 'false'}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, float):
        return f"float:{value!r}"
    if isinstance(value, str):
        return f"str:{value}"
    # Fallback for unexpected types (should not occur in valid JSON)
    return f"other:{value!r}"


def _compute_list_order_hash(items: list[Any]) -> str:
    """Hash the ordered sequence of child element hashes.

    Used to detect order volatility: if the multiset of child hashes
    is the same across runs but the ordered hash differs, the list
    exhibits order instability.
    """
    child_hashes = []
    for item in items:
        child_hashes.append(_shallow_hash(item))
    combined = "|".join(child_hashes)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def _shallow_hash(value: Any) -> str:
    """Compute a shallow hash for a list element (may be dict/list/scalar).

    For dicts and lists, uses ``json.dumps`` with sorted keys for
    deterministic output.  For scalars, delegates to ``compute_value_hash``.
    """
    if isinstance(value, (dict, list)):
        try:
            canonical = json.dumps(value, sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        except (TypeError, ValueError):
            return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()[:16]
    return compute_value_hash(value)


def _truncate_repr(value: Any) -> str:
    """Produce a truncated human-readable representation for diagnostics."""
    if value is None:
        r = "null"
    elif isinstance(value, bool):
        r = "true" if value else "false"
    elif isinstance(value, str):
        r = json.dumps(value)
    else:
        r = repr(value)
    if len(r) > _MAX_REPR_LENGTH:
        return r[: _MAX_REPR_LENGTH - 3] + "..."
    return r
