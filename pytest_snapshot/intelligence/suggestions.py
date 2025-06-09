"""Suggestion engine that translates instability findings into actions.

The engine maps ``InstabilityFinding`` objects to ``Suggestion`` objects
with concrete user-facing recommendations.  P0 supports three suggestion
types: sanitizer hints, JSON mask hints, and relational sanitizer hints.

P1 (INTEL-005/006) will add: alignment key candidates, order-ignore
suggestions, and snapshot slicing suggestions.

Output is deterministic: suggestions are deduplicated, filtered by
minimum confidence, and sorted in canonical order
(confidence DESC, target_path ASC, code ASC).
"""

from __future__ import annotations

from collections import defaultdict

from .findings import (
    INTEL_NUMERIC_DRIFT,
    INTEL_TIMESTAMP_PATTERN,
    INTEL_UUID_PATTERN,
    INTEL_VALUE_VOLATILE,
)
from .models import InstabilityFinding, PathVolatility, RunObservation, Suggestion

# -- Suggestion codes (P0) --------------------------------------------------

SUGGEST_SANITIZER = "suggest_sanitizer"
SUGGEST_JSON_MASK = "suggest_json_mask"
SUGGEST_RELATIONAL_SANITIZER = "suggest_relational_sanitizer"

_MIN_CONFIDENCE = 0.3


class SuggestionEngine:
    """Map instability findings to ranked, actionable suggestions.

    Priority chain (P0):
    1. Pattern-based: timestamp/UUID findings → SUGGEST_SANITIZER
    2. Mask-based: value-volatile without pattern → SUGGEST_JSON_MASK
    3. Relational: multiple correlated volatile values → SUGGEST_RELATIONAL_SANITIZER

    Suggestions with confidence < 0.3 are filtered out.
    Output is sorted by ``(confidence DESC, target_path ASC, code ASC)``.
    """

    def analyze(
        self,
        findings: list[InstabilityFinding],
        path_volatilities: list[PathVolatility],
        observations: list[RunObservation],
    ) -> list[Suggestion]:
        """Produce ranked suggestions from profiler output."""
        suggestions: list[Suggestion] = []
        handled_paths: set[str] = set()

        # Index findings by path for quick lookup
        findings_by_path: dict[str, list[InstabilityFinding]] = defaultdict(list)
        for f in findings:
            findings_by_path[f.path].append(f)

        # 1. Pattern-based suggestions (highest priority)
        for path, path_findings in sorted(findings_by_path.items()):
            pattern_suggestion = self._pattern_suggestion(path, path_findings)
            if pattern_suggestion is not None:
                suggestions.append(pattern_suggestion)
                handled_paths.add(path)

        # 2. Mask-based suggestions for remaining volatile paths
        for path, path_findings in sorted(findings_by_path.items()):
            if path in handled_paths:
                continue
            mask_suggestion = self._mask_suggestion(path, path_findings)
            if mask_suggestion is not None:
                suggestions.append(mask_suggestion)
                handled_paths.add(path)

        # 3. Relational sanitizer suggestions (correlated volatile values)
        relational = self._relational_suggestions(
            findings_by_path, handled_paths, path_volatilities,
        )
        suggestions.extend(relational)

        # Filter and sort
        suggestions = [s for s in suggestions if s.confidence >= _MIN_CONFIDENCE]
        suggestions.sort(
            key=lambda s: (-s.confidence, s.target_path, s.code),
        )
        return suggestions

    def _pattern_suggestion(
        self,
        path: str,
        path_findings: list[InstabilityFinding],
    ) -> Suggestion | None:
        """Generate a sanitizer suggestion from timestamp/UUID pattern findings."""
        codes = {f.code for f in path_findings}

        if INTEL_TIMESTAMP_PATTERN in codes:
            pattern_finding = next(
                f for f in path_findings if f.code == INTEL_TIMESTAMP_PATTERN
            )
            return Suggestion(
                code=SUGGEST_SANITIZER,
                message=(
                    f"Add a datetime sanitizer for {path} "
                    f"(timestamp pattern detected)"
                ),
                action_type="sanitize",
                target_path=path,
                confidence=pattern_finding.confidence,
                evidence_findings=tuple(sorted(
                    f.code for f in path_findings
                    if f.code in (INTEL_VALUE_VOLATILE, INTEL_TIMESTAMP_PATTERN)
                )),
                parameters=(("sanitizer_type", "datetime"),),
            )

        if INTEL_UUID_PATTERN in codes:
            pattern_finding = next(
                f for f in path_findings if f.code == INTEL_UUID_PATTERN
            )
            return Suggestion(
                code=SUGGEST_SANITIZER,
                message=(
                    f"Add a UUID sanitizer for {path} "
                    f"(UUID pattern detected)"
                ),
                action_type="sanitize",
                target_path=path,
                confidence=pattern_finding.confidence,
                evidence_findings=tuple(sorted(
                    f.code for f in path_findings
                    if f.code in (INTEL_VALUE_VOLATILE, INTEL_UUID_PATTERN)
                )),
                parameters=(("sanitizer_type", "uuid"),),
            )

        return None

    def _mask_suggestion(
        self,
        path: str,
        path_findings: list[InstabilityFinding],
    ) -> Suggestion | None:
        """Generate a JSON mask suggestion for volatile paths without patterns."""
        volatile_findings = [
            f for f in path_findings if f.code == INTEL_VALUE_VOLATILE
        ]
        if not volatile_findings:
            return None

        best = max(volatile_findings, key=lambda f: f.confidence)
        return Suggestion(
            code=SUGGEST_JSON_MASK,
            message=(
                f'Use snapshot_json_masks={{"{path}": "<MASKED>"}} '
                f"to stabilize volatile path"
            ),
            action_type="json_mask",
            target_path=path,
            confidence=best.confidence * 0.9,  # slightly lower than pattern-based
            evidence_findings=(INTEL_VALUE_VOLATILE,),
            parameters=(("mask_value", "<MASKED>"),),
        )

    def _relational_suggestions(
        self,
        findings_by_path: dict[str, list[InstabilityFinding]],
        handled_paths: set[str],
        path_volatilities: list[PathVolatility],
    ) -> list[Suggestion]:
        """Detect correlated volatile siblings and suggest relational sanitizer.

        If multiple volatile paths share the same parent and are all
        value-volatile, a relational sanitizer might be more appropriate
        than individual masks.
        """
        # Group volatile paths by parent
        parent_groups: dict[str, list[str]] = defaultdict(list)
        for pv in path_volatilities:
            if pv.volatility_class != "value_volatile":
                continue
            if pv.path in handled_paths:
                continue
            parent = _parent_path(pv.path)
            if parent:
                parent_groups[parent].append(pv.path)

        suggestions: list[Suggestion] = []
        for parent, child_paths in sorted(parent_groups.items()):
            if len(child_paths) < 2:
                continue
            # Multiple correlated volatile paths under the same parent
            confidences = []
            for cp in child_paths:
                for f in findings_by_path.get(cp, []):
                    if f.code == INTEL_VALUE_VOLATILE:
                        confidences.append(f.confidence)
            if not confidences:
                continue
            avg_confidence = sum(confidences) / len(confidences)
            suggestions.append(Suggestion(
                code=SUGGEST_RELATIONAL_SANITIZER,
                message=(
                    f"Consider a relational sanitizer for {parent} "
                    f"({len(child_paths)} correlated volatile fields)"
                ),
                action_type="relational_sanitize",
                target_path=parent,
                confidence=round(avg_confidence * 0.85, 4),
                evidence_findings=(INTEL_VALUE_VOLATILE,),
                parameters=tuple(
                    ("volatile_field", p) for p in sorted(child_paths)
                ),
            ))

        return suggestions


def _parent_path(path: str) -> str:
    """Extract the parent path from a JSONPath.

    ``$.users[*].name`` → ``$.users[*]``
    ``$.data.meta.ts`` → ``$.data.meta``
    ``$.count`` → ``$``
    ``$`` → ``""``
    """
    if "." not in path and "[" not in path:
        return ""
    # Find last dot not inside brackets
    last_dot = path.rfind(".")
    if last_dot <= 0:
        return ""
    return path[:last_dot]
