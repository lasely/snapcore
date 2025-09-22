"""End-to-end integration tests for --snapshot-profile mode.

These tests use pytester to run real pytest sessions with the snapshot plugin
and verify the full pipeline: CLI -> runtestloop -> facade -> collector -> profiler
-> suggestions -> report -> JSON sidecar.

Tests cover:
- Profile mode runs tests N times and produces terminal report
- Profile mode does NOT create snapshot files (QUAL-SAFETY)
- JSON sidecar written to disk with valid schema
- Mutual exclusivity validation (profile + update/review/prune)
- --snapshot-profile-runs < 2 validation
- Non-JSON snapshot in profile mode (graceful skip)
- Normal mode unaffected by intelligence code path
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestProfileModeBasic:
    """Core E2E: --snapshot-profile runs tests N times and produces report."""

    def test_profile_runs_and_produces_report(self, pytester, run_snapshot):
        """Full pipeline: profile 3 runs of a test with volatile timestamp."""
        pytester.makepyfile("""
            import json
            from datetime import datetime

            def test_volatile(snapshot):
                data = json.dumps({
                    "id": 42,
                    "ts": datetime.now().isoformat(),
                    "name": "Alice",
                })
                snapshot.assert_match(data)
        """)
        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=3",
        )
        result.stdout.fnmatch_lines([
            "*Snapshot Profile Run 1/3*",
            "*Snapshot Profile Run 2/3*",
            "*Snapshot Profile Run 3/3*",
            "*Snapshot Profile Report*",
        ])
        outcomes = result.parseoutcomes()
        assert outcomes.get("passed", 0) == 3
        assert outcomes.get("errors", 0) == 0
        assert outcomes.get("failed", 0) == 0

    def test_profile_shows_suggestions_for_volatile_field(self, pytester, run_snapshot):
        """Profile mode detects timestamp volatility and suggests sanitizer."""
        pytester.makepyfile("""
            import json
            from datetime import datetime

            def test_ts(snapshot):
                snapshot.assert_match(json.dumps({
                    "ts": datetime.now().isoformat(),
                    "stable": "hello",
                }))
        """)
        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=3",
        )
        assert result.parseoutcomes().get("passed", 0) == 3
        assert result.parseoutcomes().get("failed", 0) == 0
        result.stdout.fnmatch_lines(["*sanitizer*timestamp*"])

    def test_profile_multiple_tests(self, pytester, run_snapshot):
        """Profile mode handles multiple test functions."""
        pytester.makepyfile("""
            import json
            from datetime import datetime

            def test_a(snapshot):
                snapshot.assert_match(json.dumps({"ts": datetime.now().isoformat()}))

            def test_b(snapshot):
                snapshot.assert_match(json.dumps({"name": "stable"}))
        """)
        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=2",
        )
        assert result.parseoutcomes().get("passed", 0) == 4
        assert result.parseoutcomes().get("failed", 0) == 0


class TestQualSafety:
    """QUAL-SAFETY: profile mode NEVER creates or modifies snapshot files."""

    def test_no_snapshot_files_created(self, pytester, run_snapshot):
        """Profile mode must not create any snapshot files."""
        pytester.makepyfile("""
            import json

            def test_hello(snapshot):
                snapshot.assert_match(json.dumps({"greeting": "hello"}))
        """)
        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=3",
        )
        assert result.parseoutcomes().get("passed", 0) == 3 and result.parseoutcomes().get("failed", 0) == 0

        snap_dir = pytester.path / "__snapshots__"
        if snap_dir.exists():
            files = list(snap_dir.rglob("*.txt"))
            assert files == [], f"Snapshot files created in profile mode: {files}"

    def test_existing_snapshots_not_modified(self, pytester, run_snapshot):
        """Profile mode must not modify existing snapshot files."""
        pytester.makepyfile("""
            import json

            def test_hello(snapshot):
                snapshot.assert_match(json.dumps({"greeting": "hello"}))
        """)
        run_snapshot()

        snap_dir = pytester.path / "__snapshots__"
        assert snap_dir.exists()
        files_before = {p: p.read_text() for p in snap_dir.rglob("*.txt")}
        assert len(files_before) > 0

        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=3",
        )
        assert result.parseoutcomes().get("passed", 0) == 3 and result.parseoutcomes().get("failed", 0) == 0

        files_after = {p: p.read_text() for p in snap_dir.rglob("*.txt")}
        assert files_before == files_after, "Snapshot files modified during profile mode"


class TestJsonSidecar:
    """JSON sidecar report is written to disk with valid schema."""

    def test_sidecar_created(self, pytester, run_snapshot):
        """Profile mode writes .snapshot-profile-report.json."""
        pytester.makepyfile("""
            import json

            def test_data(snapshot):
                snapshot.assert_match(json.dumps({"key": "value"}))
        """)
        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=3",
        )
        assert result.parseoutcomes().get("passed", 0) == 3 and result.parseoutcomes().get("failed", 0) == 0

        sidecar = pytester.path / ".snapshot-profile-report.json"
        assert sidecar.exists(), "JSON sidecar not created"

        data = json.loads(sidecar.read_text())
        assert "schema_version" in data
        assert data["schema_version"] == "1.0"
        assert "targets" in data
        assert len(data["targets"]) == 1

    def test_sidecar_contains_findings_and_suggestions(self, pytester, run_snapshot):
        """Sidecar JSON includes findings and suggestions for volatile data."""
        pytester.makepyfile("""
            import json
            from datetime import datetime

            def test_volatile(snapshot):
                snapshot.assert_match(json.dumps({
                    "ts": datetime.now().isoformat(),
                    "name": "stable",
                }))
        """)
        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=3",
        )

        sidecar = pytester.path / ".snapshot-profile-report.json"
        data = json.loads(sidecar.read_text())
        target = data["targets"][0]

        assert len(target["findings"]) > 0
        assert any(f["code"] == "intel_value_volatile" for f in target["findings"])
        assert "suggestions" in target

    def test_sidecar_custom_output_dir(self, pytester, run_snapshot):
        """--snapshot-profile-output writes sidecar to custom directory."""
        pytester.makepyfile("""
            import json

            def test_data(snapshot):
                snapshot.assert_match(json.dumps({"k": "v"}))
        """)
        output_dir = pytester.path / "custom_output"
        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=2",
            f"--snapshot-profile-output={output_dir}",
        )

        sidecar = output_dir / ".snapshot-profile-report.json"
        assert sidecar.exists(), f"Sidecar not found at {sidecar}"


class TestValidation:
    """CLI option mutual exclusivity and validation."""

    def test_profile_with_update_errors(self, pytester, run_snapshot):
        pytester.makepyfile("def test_x(snapshot): snapshot.assert_match('x')")
        result = run_snapshot("--snapshot-profile", "--snapshot-update")
        result.stderr.fnmatch_lines(["*mutually exclusive*"])

    def test_profile_with_review_errors(self, pytester, run_snapshot):
        pytester.makepyfile("def test_x(snapshot): snapshot.assert_match('x')")
        result = run_snapshot("--snapshot-profile", "--snapshot-review")
        result.stderr.fnmatch_lines(["*mutually exclusive*"])

    def test_profile_with_review_ci_errors(self, pytester, run_snapshot):
        pytester.makepyfile("def test_x(snapshot): snapshot.assert_match('x')")
        result = run_snapshot("--snapshot-profile", "--snapshot-review-ci")
        result.stderr.fnmatch_lines(["*mutually exclusive*"])

    def test_profile_with_prune_errors(self, pytester, run_snapshot):
        pytester.makepyfile("def test_x(snapshot): snapshot.assert_match('x')")
        result = run_snapshot("--snapshot-profile", "--snapshot-prune")
        result.stderr.fnmatch_lines(["*mutually exclusive*"])

    def test_profile_runs_below_2_errors(self, pytester, run_snapshot):
        pytester.makepyfile("def test_x(snapshot): snapshot.assert_match('x')")
        result = run_snapshot("--snapshot-profile", "--snapshot-profile-runs=1")
        result.stderr.fnmatch_lines(["*at least 2*"])

    def test_profile_with_xdist_errors(self, pytester, run_snapshot):
        """Profile mode is mutually exclusive with pytest-xdist (TEST-5)."""
        pytester.makepyfile("def test_x(snapshot): snapshot.assert_match('x')")
        pytester.makeconftest("""
            def pytest_configure(config):
                if not hasattr(config.option, 'numprocesses'):
                    config.option.numprocesses = 2
        """)
        result = run_snapshot("--snapshot-profile")
        result.stderr.fnmatch_lines(["*not supported with pytest-xdist*"])


class TestNonJsonProfile:
    """Non-JSON snapshots in profile mode are handled gracefully."""

    def test_non_json_skipped_gracefully(self, pytester, run_snapshot):
        """Non-JSON (repr) snapshots produce INTEL_NON_JSON_SKIPPED, not crash."""
        pytester.makepyfile("""
            def test_int(snapshot):
                snapshot.assert_match(42)
        """)
        pytester.makeini("[pytest]\nsnapshot_repr_policy = allow")
        result = run_snapshot(
            "--snapshot-profile",
            "--snapshot-profile-runs=3",
        )
        assert result.parseoutcomes().get("passed", 0) == 3 and result.parseoutcomes().get("failed", 0) == 0
        result.stdout.fnmatch_lines(["*Snapshot Profile Report*"])


class TestNormalModeUnaffected:
    """Normal (non-profile) test execution is unaffected by intelligence code."""

    def test_normal_create_and_match(self, pytester, run_snapshot):
        """Standard snapshot workflow still works with intelligence code loaded."""
        pytester.makepyfile("""
            import json

            def test_hello(snapshot):
                snapshot.assert_match(json.dumps({"greeting": "hello"}))
        """)
        result1 = run_snapshot()
        result1.assert_outcomes(passed=1)

        result2 = run_snapshot()
        result2.assert_outcomes(passed=1)

        assert "Snapshot Profile Report" not in result2.stdout.str()

    def test_normal_mismatch_still_fails(self, pytester, run_snapshot):
        """Snapshot mismatches still fail in normal mode."""
        pytester.makepyfile("""
            import json
            from pathlib import Path

            def test_mismatch(snapshot):
                flag = Path(__file__).parent / "_run2"
                val = "v2" if flag.exists() else "v1"
                snapshot.assert_match(json.dumps({"val": val}))
        """)
        run_snapshot()
        (pytester.path / "_run2").write_text("")
        result = run_snapshot()
        result.assert_outcomes(failed=1)
