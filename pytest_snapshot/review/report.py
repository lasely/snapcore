"""Terminal and JSON reporting for collected snapshot review state.

The report layer turns pending changes and policy findings into stable output
formats suitable for human review in CI logs and for machine consumption by
automation tooling.
"""

from __future__ import annotations

import json
from typing import IO

from ..models import AssertionDiagnostics, PolicyFinding
from .collector import ChangeType, PendingChange


class ReviewReport:
    """Render collected review data as terminal text or JSON."""

    def __init__(
        self,
        pending: list[PendingChange],
        *,
        policy_findings: list[PolicyFinding] | None = None,
    ) -> None:
        self._pending = pending
        self._policy_findings = policy_findings or []

    def render_terminal(self) -> str:
        """Render a concise terminal-oriented review summary."""
        if not self._pending and not self._policy_findings:
            return "No snapshot changes to review.\n"

        created = [c for c in self._pending if c.change_type == ChangeType.CREATED]
        modified = [c for c in self._pending if c.change_type == ChangeType.MODIFIED]
        lines: list[str] = ["=== Snapshot Review Report ===\n"]

        if self._policy_findings:
            lines.append("Policy findings:")
            for finding in self._policy_findings:
                severity = finding.severity.upper()
                lines.append(f"  [{severity}] {finding.code}: {finding.message}")
                if finding.path is not None:
                    lines.append(f"    path: {finding.path}")
            lines.append("")

        for change in self._pending:
            key = change.key
            location = f"{key.module}::{key.test_name}"
            if key.class_name:
                location = f"{key.module}::{key.class_name}::{key.test_name}"

            lines.append(f"[{change.change_type.value.upper()}] {location} / {key.snapshot_name}")
            if change.diagnostics is not None:
                lines.extend(self._format_terminal_diagnostics(change.diagnostics))

            if change.change_type == ChangeType.CREATED:
                actual_lines = change.actual.count("\n") + 1
                lines.append(f"  + {actual_lines} lines")
            else:
                if change.expected is not None:
                    exp_lines = change.expected.count("\n") + 1
                    act_lines = change.actual.count("\n") + 1
                    lines.append(f"  expected: {exp_lines} lines, actual: {act_lines} lines")
                if change.diff:
                    diff_lines = change.diff.splitlines()
                    for line in diff_lines[:10]:
                        lines.append(f"  {line}")
                    if len(diff_lines) > 10:
                        lines.append(f"  ... ({len(diff_lines) - 10} more lines)")

            lines.append("")

        lines.append(
            f"Total: {len(self._pending)} pending ({len(created)} created, {len(modified)} modified)"
        )
        if self._policy_findings:
            lines.append(f"Policy findings: {len(self._policy_findings)}")
        lines.append("")
        lines.append("Run `pytest --snapshot-review` to accept or reject interactively.")
        lines.append("Run `pytest --snapshot-update` to accept all.")
        lines.append("")
        return "\n".join(lines)

    def render_json(self) -> str:
        """Serialize the collected state into a stable JSON report schema."""
        created = sum(1 for c in self._pending if c.change_type == ChangeType.CREATED)
        modified = sum(1 for c in self._pending if c.change_type == ChangeType.MODIFIED)

        changes: list[dict[str, object]] = []
        for change in self._pending:
            key = change.key
            location = f"{key.module}::{key.test_name}"
            if key.class_name:
                location = f"{key.module}::{key.class_name}::{key.test_name}"

            entry: dict[str, object] = {
                "test_id": location,
                "snapshot_name": key.snapshot_name,
                "change_type": change.change_type.value,
                "actual_lines": change.actual.count("\n") + 1,
            }
            if change.expected is not None:
                entry["expected_lines"] = change.expected.count("\n") + 1
            if change.diff:
                entry["diff"] = change.diff
            if change.diagnostics is not None:
                entry["diagnostics"] = self._serialize_diagnostics(change.diagnostics)
            changes.append(entry)

        report = {
            "pending_changes": changes,
            "policy_findings": [
                self._serialize_policy_finding(finding)
                for finding in self._policy_findings
            ],
            "summary": {
                "total": len(self._pending),
                "created": created,
                "modified": modified,
                "policy_findings": len(self._policy_findings),
            },
        }
        return json.dumps(report, indent=2, ensure_ascii=False)

    def print_terminal(self, output: IO[str]) -> None:
        """Write the terminal report to ``output`` and flush the stream."""
        output.write(self.render_terminal())
        output.flush()

    def print_json(self, output: IO[str]) -> None:
        """Write the JSON report to ``output`` and flush the stream."""
        output.write(self.render_json())
        output.write("\n")
        output.flush()

    def _serialize_policy_finding(self, finding: PolicyFinding) -> dict[str, object]:
        """Convert a policy finding into the JSON report structure."""
        data: dict[str, object] = {
            "code": finding.code,
            "message": finding.message,
            "severity": finding.severity,
        }
        if finding.test_id is not None:
            data["test_id"] = finding.test_id
        if finding.snapshot_name is not None:
            data["snapshot_name"] = finding.snapshot_name
        if finding.path is not None:
            data["path"] = str(finding.path)
        return data

    def _format_terminal_diagnostics(self, diagnostics: AssertionDiagnostics) -> list[str]:
        """Render diagnostics as compact human-readable terminal lines."""
        serializer = diagnostics.serializer_name
        if diagnostics.serializer_priority is not None:
            serializer += f"@{diagnostics.serializer_priority}"
        if diagnostics.serializer_forced:
            serializer += " forced"

        sanitizers = ", ".join(diagnostics.sanitizer_names) if diagnostics.sanitizer_names else "none"
        diff_mode = diagnostics.effective_diff_mode or diagnostics.diff_mode
        if diagnostics.effective_diff_mode and diagnostics.effective_diff_mode != diagnostics.diff_mode:
            diff_mode = f"{diff_mode} (requested {diagnostics.diff_mode})"

        lines = [f"  diagnostics: serializer={serializer}; sanitizers={sanitizers}; diff={diff_mode}"]
        if diagnostics.repr_fallback_used:
            lines.append("  diagnostics: repr_fallback=yes")
        if diagnostics.diff_fallback_reason is not None:
            lines.append(f"  diagnostics: diff_fallback={diagnostics.diff_fallback_reason}")
        if diagnostics.snapshot_path is not None:
            lines.append(f"  path: {diagnostics.snapshot_path}")
        return lines

    def _serialize_diagnostics(self, diagnostics: AssertionDiagnostics) -> dict[str, object]:
        """Convert runtime diagnostics into the JSON report structure."""
        data: dict[str, object] = {
            "serializer_name": diagnostics.serializer_name,
            "serializer_forced": diagnostics.serializer_forced,
            "repr_fallback_used": diagnostics.repr_fallback_used,
            "sanitizer_names": list(diagnostics.sanitizer_names),
            "sanitizer_profile": diagnostics.sanitizer_profile,
            "diff_mode": diagnostics.diff_mode,
        }
        if diagnostics.serializer_priority is not None:
            data["serializer_priority"] = diagnostics.serializer_priority
        if diagnostics.effective_diff_mode is not None:
            data["effective_diff_mode"] = diagnostics.effective_diff_mode
        if diagnostics.diff_fallback_reason is not None:
            data["diff_fallback_reason"] = diagnostics.diff_fallback_reason
        if diagnostics.snapshot_path is not None:
            data["snapshot_path"] = str(diagnostics.snapshot_path)
        return data
