"""Builder functions for intelligence-specific findings.

Centralizes finding construction so instability codes and message templates
are not duplicated across the profiler and reporting layers.  Follows the
same pattern as ``alignment/findings.py`` and ``policy.py``.
"""

from __future__ import annotations

from .models import InstabilityFinding

# -- Instability codes ------------------------------------------------------
#
# INTEL_VALUE_VOLATILE       Scalar value changes across runs.
# INTEL_PRESENCE_VOLATILE    Path appears/disappears across runs.
# INTEL_SHAPE_VOLATILE       Value type changes across runs.
# INTEL_ORDER_VOLATILE       List child ordering changes across runs.
# INTEL_TIMESTAMP_PATTERN    Volatile value matches timestamp pattern.
# INTEL_UUID_PATTERN         Volatile value matches UUID pattern.
# INTEL_NUMERIC_DRIFT        Numeric value drifts within small range.
# INTEL_STABLE_PATH          Path is completely stable (informational).
# INTEL_NON_JSON_SKIPPED     Non-JSON serializer, structural analysis skipped.
# INTEL_INSUFFICIENT_RUNS    Fewer than min_runs, confidence is low.

INTEL_VALUE_VOLATILE = "intel_value_volatile"
INTEL_PRESENCE_VOLATILE = "intel_presence_volatile"
INTEL_SHAPE_VOLATILE = "intel_shape_volatile"
INTEL_ORDER_VOLATILE = "intel_order_volatile"
INTEL_TIMESTAMP_PATTERN = "intel_timestamp_pattern"
INTEL_UUID_PATTERN = "intel_uuid_pattern"
INTEL_NUMERIC_DRIFT = "intel_numeric_drift"
INTEL_STABLE_PATH = "intel_stable_path"
INTEL_NON_JSON_SKIPPED = "intel_non_json_skipped"
INTEL_INSUFFICIENT_RUNS = "intel_insufficient_runs"


def build_value_volatile_finding(
    *,
    path: str,
    total_runs: int,
    distinct_values: int,
    value_changes: int,
    confidence: float,
) -> InstabilityFinding:
    """Scalar value at path changes across runs."""
    return InstabilityFinding(
        code=INTEL_VALUE_VOLATILE,
        message=(
            f"Path {path} changed in {value_changes}/{total_runs - 1} "
            f"adjacent runs ({distinct_values} distinct values)"
        ),
        severity="warning",
        path=path,
        volatility_class="value_volatile",
        evidence=(
            f"{distinct_values} distinct values across {total_runs} runs",
            f"{value_changes} value changes in {total_runs - 1} adjacent pairs",
        ),
        confidence=confidence,
    )


def build_presence_volatile_finding(
    *,
    path: str,
    total_runs: int,
    presence_count: int,
    confidence: float,
) -> InstabilityFinding:
    """Path appears in some runs but not others."""
    return InstabilityFinding(
        code=INTEL_PRESENCE_VOLATILE,
        message=(
            f"Path {path} present in {presence_count}/{total_runs} runs"
        ),
        severity="warning",
        path=path,
        volatility_class="presence_volatile",
        evidence=(
            f"Present in {presence_count} of {total_runs} runs",
        ),
        confidence=confidence,
    )


def build_shape_volatile_finding(
    *,
    path: str,
    total_runs: int,
    type_changes: int,
    confidence: float,
) -> InstabilityFinding:
    """Value type at path changes across runs."""
    return InstabilityFinding(
        code=INTEL_SHAPE_VOLATILE,
        message=(
            f"Path {path} type changed in {type_changes}/{total_runs} runs"
        ),
        severity="warning",
        path=path,
        volatility_class="shape_volatile",
        evidence=(
            f"Type changed in {type_changes} of {total_runs} runs",
        ),
        confidence=confidence,
    )


def build_order_volatile_finding(
    *,
    path: str,
    total_runs: int,
    order_changes: int,
    confidence: float,
) -> InstabilityFinding:
    """List child ordering changes across runs (content stable)."""
    return InstabilityFinding(
        code=INTEL_ORDER_VOLATILE,
        message=(
            f"List at {path} reordered in {order_changes}/{total_runs - 1} "
            f"adjacent runs"
        ),
        severity="warning",
        path=path,
        volatility_class="order_volatile",
        evidence=(
            f"Order changed in {order_changes} of {total_runs - 1} adjacent pairs",
        ),
        confidence=confidence,
    )


def build_timestamp_pattern_finding(
    *,
    path: str,
    total_runs: int,
    match_count: int,
    confidence: float,
) -> InstabilityFinding:
    """Volatile value matches timestamp pattern (ISO-8601, epoch)."""
    return InstabilityFinding(
        code=INTEL_TIMESTAMP_PATTERN,
        message=(
            f"Values at {path} match timestamp pattern "
            f"({match_count}/{total_runs} values)"
        ),
        severity="info",
        path=path,
        volatility_class="value_volatile",
        evidence=(
            f"{match_count}/{total_runs} values match ISO-8601 or epoch pattern",
        ),
        confidence=confidence,
    )


def build_uuid_pattern_finding(
    *,
    path: str,
    total_runs: int,
    match_count: int,
    confidence: float,
) -> InstabilityFinding:
    """Volatile value matches UUID/GUID pattern."""
    return InstabilityFinding(
        code=INTEL_UUID_PATTERN,
        message=(
            f"Values at {path} match UUID pattern "
            f"({match_count}/{total_runs} values)"
        ),
        severity="info",
        path=path,
        volatility_class="value_volatile",
        evidence=(
            f"{match_count}/{total_runs} values match UUID pattern",
        ),
        confidence=confidence,
    )


def build_numeric_drift_finding(
    *,
    path: str,
    total_runs: int,
    min_value: float,
    max_value: float,
    confidence: float,
) -> InstabilityFinding:
    """Numeric value drifts within a small range."""
    return InstabilityFinding(
        code=INTEL_NUMERIC_DRIFT,
        message=(
            f"Numeric value at {path} drifts between "
            f"{min_value} and {max_value} across {total_runs} runs"
        ),
        severity="info",
        path=path,
        volatility_class="value_volatile",
        evidence=(
            f"Range: [{min_value}, {max_value}] across {total_runs} runs",
        ),
        confidence=confidence,
    )


def build_stable_path_finding(
    *,
    path: str,
    total_runs: int,
) -> InstabilityFinding:
    """Path is completely stable across all runs (informational)."""
    return InstabilityFinding(
        code=INTEL_STABLE_PATH,
        message=f"Path {path} stable across {total_runs} runs",
        severity="info",
        path=path,
        volatility_class="stable",
        evidence=(f"Stable across {total_runs} runs",),
        confidence=1.0,
    )


def build_non_json_skipped_finding(
    *,
    serializer_name: str,
    test_id: str | None = None,
    snapshot_name: str | None = None,
) -> InstabilityFinding:
    """Non-JSON serializer used, structural analysis skipped."""
    return InstabilityFinding(
        code=INTEL_NON_JSON_SKIPPED,
        message=(
            f"Non-JSON serializer ({serializer_name}), "
            f"structural analysis skipped"
        ),
        severity="info",
        path="$",
        volatility_class="stable",
        evidence=(f"Serializer: {serializer_name}",),
        confidence=1.0,
        test_id=test_id,
        snapshot_name=snapshot_name,
    )


def build_insufficient_runs_finding(
    *,
    total_runs: int,
    min_runs: int,
) -> InstabilityFinding:
    """Fewer than min_runs, confidence is low."""
    return InstabilityFinding(
        code=INTEL_INSUFFICIENT_RUNS,
        message=(
            f"Only {total_runs} run(s) collected "
            f"(minimum {min_runs} recommended for reliable analysis)"
        ),
        severity="warning",
        path="$",
        volatility_class="stable",
        evidence=(f"{total_runs} runs < minimum {min_runs}",),
        confidence=min(1.0, total_runs / min_runs),
    )
