"""Terminal and JSON rendering for intelligence analysis reports.

Produces human-readable terminal summaries and machine-readable JSON
sidecar files from ``AnalysisReport`` objects.  The JSON schema is
stable and tested via contract tests (QUAL-003).
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import AnalysisReport, InstabilityFinding, PathVolatility, Suggestion

_SIDECAR_FILENAME = ".snapshot-profile-report.json"
_SCHEMA_VERSION = "1.0"


class IntelligenceReport:
    """Render profiler analysis as terminal text or JSON."""

    def __init__(self, reports: list[AnalysisReport]) -> None:
        self._reports = reports

    def render_terminal(self) -> str:
        """Render human-readable terminal summary."""
        if not self._reports:
            return "=== Snapshot Profile Report ===\nNo snapshot targets profiled.\n"

        total_targets = len(self._reports)
        total_runs = self._reports[0].total_runs if self._reports else 0
        lines = [
            "=== Snapshot Profile Report ===",
            f"Profiled {total_targets} snapshot target(s) across {total_runs} runs",
            "",
        ]

        for report in self._reports:
            lines.extend(self._render_target_terminal(report))
            lines.append("")

        return "\n".join(lines)

    def render_json(self) -> str:
        """Render machine-readable JSON report."""
        data = {
            "schema_version": _SCHEMA_VERSION,
            "targets": [self._serialize_report(r) for r in self._reports],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def write_json_sidecar(self, output_dir: Path) -> Path:
        """Write JSON report to ``{output_dir}/.snapshot-profile-report.json``.

        Creates parent directories if they don't exist.  Returns the
        path to the written file.

        Raises
        ------
        OSError
            If the file cannot be written (permission denied, etc.).
            The caller should catch and warn rather than crash.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / _SIDECAR_FILENAME
        path.write_text(self.render_json(), encoding="utf-8")
        return path

    # -- Terminal rendering helpers ------------------------------------------

    def _render_target_terminal(self, report: AnalysisReport) -> list[str]:
        """Render one target's analysis for the terminal."""
        key = report.key
        test_id = key.format_test_id()

        # Summary counts
        summary = dict(report.summary)
        total_paths = summary.get("total_paths", "?")
        stable_paths = summary.get("stable_paths", "?")
        volatile_paths = summary.get("volatile_paths", "?")

        lines = [
            f"--- {test_id} / {key.snapshot_name} ---",
            f"  {total_paths} paths analyzed: {stable_paths} stable, {volatile_paths} volatile",
        ]

        # Findings (skip info-level for brevity, show warning+error)
        important_findings = [
            f for f in report.findings if f.severity in ("warning", "error")
        ]
        if important_findings:
            lines.append("")
            lines.append("  Findings:")
            for f in important_findings:
                tag = f.severity.upper()
                lines.append(f"    [{tag}] {f.code}: {f.message}")

        # Info findings (pattern detections)
        info_findings = [f for f in report.findings if f.severity == "info"]
        if info_findings:
            for f in info_findings:
                lines.append(f"    [INFO] {f.code}: {f.message}")

        # Suggestions
        if report.suggestions:
            lines.append("")
            lines.append("  Suggestions:")
            for i, s in enumerate(report.suggestions, 1):
                lines.append(f"    {i}. [{s.confidence:.2f}] {s.message}")

        return lines

    # -- JSON serialization helpers ------------------------------------------

    def _serialize_report(self, report: AnalysisReport) -> dict:
        """Serialize one AnalysisReport to a JSON-compatible dict."""
        key = report.key

        return {
            "test_id": key.format_test_id(),
            "snapshot_name": key.snapshot_name,
            "total_runs": report.total_runs,
            "path_volatilities": [
                self._serialize_volatility(v) for v in report.path_volatilities
            ],
            "findings": [
                self._serialize_finding(f) for f in report.findings
            ],
            "suggestions": [
                self._serialize_suggestion(s) for s in report.suggestions
            ],
            "summary": dict(report.summary),
        }

    @staticmethod
    def _serialize_volatility(v: PathVolatility) -> dict:
        return {
            "path": v.path,
            "volatility_class": v.volatility_class,
            "total_runs": v.total_runs,
            "distinct_values": v.distinct_values,
            "presence_count": v.presence_count,
            "type_changes": v.type_changes,
            "value_changes": v.value_changes,
            "order_changes": v.order_changes,
            "confidence": v.confidence,
        }

    @staticmethod
    def _serialize_finding(f: InstabilityFinding) -> dict:
        data: dict = {
            "code": f.code,
            "message": f.message,
            "severity": f.severity,
            "path": f.path,
            "volatility_class": f.volatility_class,
            "confidence": f.confidence,
            "evidence": list(f.evidence),
        }
        if f.test_id is not None:
            data["test_id"] = f.test_id
        if f.snapshot_name is not None:
            data["snapshot_name"] = f.snapshot_name
        return data

    @staticmethod
    def _serialize_suggestion(s: Suggestion) -> dict:
        data: dict = {
            "code": s.code,
            "message": s.message,
            "action_type": s.action_type,
            "target_path": s.target_path,
            "confidence": s.confidence,
            "evidence_findings": list(s.evidence_findings),
        }
        if s.parameters is not None:
            # Group duplicate keys into arrays to preserve all values.
            # Single-valued keys stay as strings for backward compatibility.
            grouped: dict[str, list[str]] = {}
            for k, v in s.parameters:
                grouped.setdefault(k, []).append(v)
            data["parameters"] = {
                k: vs[0] if len(vs) == 1 else vs
                for k, vs in grouped.items()
            }
        return data
