from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .config import SnapshotConfig
from .diff import StructuralDiffRenderer, TextDiffRenderer
from .facade import SnapshotAssertion, TestLocation
from .policy import build_orphan_policy_findings
from .review.collector import SnapshotCollector
from .sanitizers import SanitizerRegistry
from .serializers import create_default_registry
from .storage import FileStorageBackend, NamingPolicy

if TYPE_CHECKING:
    from .protocols import Sanitizer, Serializer


_ALLOWED_MISSING_POLICIES = {"create", "fail", "review"}
_ALLOWED_REPR_POLICIES = {"allow", "warn", "forbid"}
_ALLOWED_SANITIZER_PROFILES = {"none", "standard", "relational"}
_ALLOWED_XDIST_POLICIES = {"fail"}

def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("snapshot", "Snapshot testing")
    group.addoption(
        "--snapshot-update",
        action="store_true",
        default=False,
        help="Update all snapshots instead of comparing",
    )
    group.addoption(
        "--snapshot-review",
        action="store_true",
        default=False,
        help="Review snapshot changes interactively after test run",
    )
    group.addoption(
        "--snapshot-review-ci",
        action="store_true",
        default=False,
        help="Generate snapshot change report (non-interactive, for CI)",
    )
    group.addoption(
        "--snapshot-strict",
        action="store_true",
        default=False,
        help="Fail when a snapshot is missing instead of creating it",
    )
    group.addoption(
        "--snapshot-prune-report",
        action="store_true",
        default=False,
        help="Report orphaned snapshot files without deleting them",
    )
    group.addoption(
        "--snapshot-prune",
        action="store_true",
        default=False,
        help="Delete orphaned snapshot files after the test run",
    )

    parser.addini(
        "snapshot_dir",
        default="__snapshots__",
        help="Directory for snapshot storage (relative to pytest invocation directory)",
    )
    parser.addini(
        "snapshot_default_serializer",
        default="",
        help="Force a specific serializer by name",
    )
    parser.addini(
        "snapshot_diff_mode",
        default="text",
        help="Diff renderer mode: 'text' (unified diff) or 'structural' (JSON-path diff)",
    )
    parser.addini(
        "snapshot_missing_policy",
        default="create",
        help="Missing snapshot policy: 'create', 'fail', or 'review'",
    )
    parser.addini(
        "snapshot_repr_policy",
        default="warn",
        help="repr fallback policy: 'allow', 'warn', or 'forbid'",
    )
    parser.addini(
        "snapshot_sanitizer_profile",
        default="none",
        help="Built-in sanitizer profile: 'none', 'standard', or 'relational'",
    )
    parser.addini(
        "snapshot_xdist_policy",
        default="fail",
        help="Behavior under pytest-xdist for unsupported workflows",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Validate option combinations and create session-scoped collector."""
    _validate_runtime_options(config)
    config._snapshot_collector = SnapshotCollector()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Run review session or print CI report after all tests complete."""
    config = session.config
    collector: SnapshotCollector = config._snapshot_collector

    review = config.getoption("--snapshot-review", default=False)
    review_ci = config.getoption("--snapshot-review-ci", default=False)
    prune_report = config.getoption("--snapshot-prune-report", default=False)
    prune = config.getoption("--snapshot-prune", default=False)

    if not (review or review_ci or prune_report or prune):
        return

    snap_config = _build_config(config)
    storage = FileStorageBackend(NamingPolicy(), snap_config.snapshot_dir)

    if prune_report or prune:
        orphan_paths = storage.orphan_files(collector.touched_paths)
        orphan_findings = build_orphan_policy_findings(orphan_paths)
        for finding in orphan_findings:
            collector.record_policy_finding(finding)
        if prune_report:
            _print_prune_report(
                sys.stdout,
                snapshot_dir=snap_config.snapshot_dir,
                touched_paths=collector.touched_paths,
                orphan_paths=orphan_paths,
            )
            if orphan_paths and session.exitstatus == 0:
                session.exitstatus = 1
        else:
            _prune_orphan_files(
                storage,
                snapshot_dir=snap_config.snapshot_dir,
                orphan_paths=orphan_paths,
                output=sys.stdout,
            )

    if not (review or review_ci):
        return

    if not collector.has_changes:
        if review:
            sys.stdout.write("\nNo snapshot changes to review.\n")
        return

    if review_ci:
        from .review.report import ReviewReport
        report = ReviewReport(
            collector.pending,
            policy_findings=collector.policy_findings,
        )
        report.print_terminal(sys.stdout)
        session.exitstatus = 1

    elif review:
        from .review.session import ReviewSession

        real_out = getattr(sys, "__stdout__", None) or sys.stdout
        real_in = getattr(sys, "__stdin__", None) or sys.stdin

        def _real_input(prompt: str) -> str:
            """Read a line from the real terminal, bypassing pytest capture."""
            real_out.write(prompt)
            real_out.flush()
            line = real_in.readline()
            if not line:
                raise EOFError("EOF on stdin")
            return line.rstrip("\n")

        review_session = ReviewSession(
            pending=collector.pending,
            storage=storage,
            output=real_out,
            input_fn=_real_input,
        )
        result = review_session.run()
        if result.has_skipped:
            session.exitstatus = 1

@pytest.fixture
def snapshot(request: pytest.FixtureRequest) -> SnapshotAssertion:
    """Provide a SnapshotAssertion instance for the current test."""
    config = _build_config(request.config)
    serializer_registry = create_default_registry()
    sanitizer_registry = SanitizerRegistry()

    for s in _get_user_serializers(request):
        serializer_registry.register(s, priority=0)

    for s in _get_user_sanitizers(request):
        sanitizer_registry.register(s)

    storage = FileStorageBackend(NamingPolicy(), config.snapshot_dir)
    differ = _build_diff_renderer(config)
    test_location = _extract_test_location(request.node)

    collector: SnapshotCollector | None = getattr(
        request.config, "_snapshot_collector", None,
    )

    return SnapshotAssertion(
        config,
        serializer_registry,
        sanitizer_registry,
        storage,
        differ,
        test_location=test_location,
        collector=collector,
    )

def _build_config(pytestconfig: pytest.Config) -> SnapshotConfig:
    invocation_dir = getattr(getattr(pytestconfig, "invocation_params", None), "dir", None)
    base_dir = Path(invocation_dir) if invocation_dir is not None else Path(pytestconfig.rootdir)
    snapshot_dir_raw = pytestconfig.getini("snapshot_dir")
    snapshot_dir = Path(snapshot_dir_raw)
    if not snapshot_dir.is_absolute():
        snapshot_dir = (base_dir / snapshot_dir).resolve()

    default_serializer = pytestconfig.getini("snapshot_default_serializer") or None

    diff_mode = _normalized_ini_value(pytestconfig, "snapshot_diff_mode", "text")
    missing_policy = _normalized_ini_value(pytestconfig, "snapshot_missing_policy", "create")
    if pytestconfig.getoption("--snapshot-strict", default=False):
        missing_policy = "fail"
    repr_policy = _normalized_ini_value(pytestconfig, "snapshot_repr_policy", "warn")
    sanitizer_profile = _normalized_ini_value(pytestconfig, "snapshot_sanitizer_profile", "none")
    xdist_policy = _normalized_ini_value(pytestconfig, "snapshot_xdist_policy", "fail")

    return SnapshotConfig(
        snapshot_dir=snapshot_dir,
        update_mode=pytestconfig.getoption("--snapshot-update", default=False),
        review_mode=pytestconfig.getoption("--snapshot-review", default=False),
        review_ci_mode=pytestconfig.getoption("--snapshot-review-ci", default=False),
        diff_mode=diff_mode,
        default_serializer_name=default_serializer,
        missing_policy=missing_policy,
        repr_policy=repr_policy,
        sanitizer_profile=sanitizer_profile,
        xdist_policy=xdist_policy,
    )


def _build_diff_renderer(config: SnapshotConfig) -> TextDiffRenderer | StructuralDiffRenderer:
    """Construct the appropriate diff renderer based on config."""
    text_renderer = TextDiffRenderer()
    if config.diff_mode == "structural":
        return StructuralDiffRenderer(text_fallback=text_renderer)
    return text_renderer


def _extract_test_location(node: pytest.Item) -> TestLocation:
    module_name = node.module.__name__ if node.module else "unknown"
    class_name = node.cls.__name__ if node.cls else None
    test_name = node.name
    return TestLocation(module=module_name, class_name=class_name, test_name=test_name)


def _get_user_serializers(request: pytest.FixtureRequest) -> list[Serializer]:
    try:
        return request.getfixturevalue("snapshot_serializers")
    except pytest.FixtureLookupError:
        return []


def _get_user_sanitizers(request: pytest.FixtureRequest) -> list[Sanitizer]:
    try:
        return request.getfixturevalue("snapshot_sanitizers")
    except pytest.FixtureLookupError:
        return []


def _validate_runtime_options(config: pytest.Config) -> None:
    update = config.getoption("--snapshot-update", default=False)
    review = config.getoption("--snapshot-review", default=False)
    review_ci = config.getoption("--snapshot-review-ci", default=False)
    prune_report = config.getoption("--snapshot-prune-report", default=False)
    prune = config.getoption("--snapshot-prune", default=False)
    strict = config.getoption("--snapshot-strict", default=False)

    if update and (review or review_ci or prune_report or prune):
        raise pytest.UsageError(
            "--snapshot-update is mutually exclusive with review and prune modes."
        )

    if prune and prune_report:
        raise pytest.UsageError(
            "--snapshot-prune and --snapshot-prune-report are mutually exclusive."
        )

    if (review or review_ci) and (prune or prune_report):
        raise pytest.UsageError(
            "Snapshot review modes cannot be combined with prune workflows."
        )

    missing_policy = _normalized_ini_value(config, "snapshot_missing_policy", "create")
    if strict:
        missing_policy = "fail"
    _validate_choice("snapshot_missing_policy", missing_policy, _ALLOWED_MISSING_POLICIES)

    repr_policy = _normalized_ini_value(config, "snapshot_repr_policy", "warn")
    _validate_choice("snapshot_repr_policy", repr_policy, _ALLOWED_REPR_POLICIES)

    sanitizer_profile = _normalized_ini_value(config, "snapshot_sanitizer_profile", "none")
    _validate_choice(
        "snapshot_sanitizer_profile",
        sanitizer_profile,
        _ALLOWED_SANITIZER_PROFILES,
    )

    xdist_policy = _normalized_ini_value(config, "snapshot_xdist_policy", "fail")
    _validate_choice("snapshot_xdist_policy", xdist_policy, _ALLOWED_XDIST_POLICIES)

    if _is_xdist_active(config) and (review or review_ci or prune or prune_report):
        raise pytest.UsageError(
            "Snapshot review and prune workflows are not supported with pytest-xdist in v1.1."
        )


def _normalized_ini_value(pytestconfig: pytest.Config, key: str, default: str) -> str:
    raw = pytestconfig.getini(key)
    value = str(raw).strip().lower() if raw is not None else ""
    return value or default


def _validate_choice(name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise pytest.UsageError(
            f"Invalid value for {name!r}: {value!r}. Allowed values: {allowed_values}."
        )


def _is_xdist_active(config: pytest.Config) -> bool:
    if hasattr(config, "workerinput"):
        return True

    option = getattr(config, "option", None)
    numprocesses = getattr(option, "numprocesses", None)
    return isinstance(numprocesses, int) and numprocesses > 0


def _print_prune_report(
    output,
    *,
    snapshot_dir: Path,
    touched_paths: set[Path],
    orphan_paths: list[Path],
) -> None:
    lines = [
        "\n=== Snapshot Prune Report ===",
        "This report is based only on snapshot paths touched in the current pytest run.",
        "Partial, filtered, or skipped runs can produce false positives.",
        "",
    ]

    if orphan_paths:
        for path in orphan_paths:
            lines.append(f"Orphan: {path.relative_to(snapshot_dir)}")
        lines.extend(
            [
                "",
                (
                    f"Found {len(orphan_paths)} orphaned snapshot(s) "
                    f"out of {len(touched_paths)} touched path(s)."
                ),
                "Run `pytest --snapshot-prune` to delete the reported files.",
            ]
        )
    else:
        lines.extend(
            [
                "No orphaned snapshot files found.",
                f"Touched snapshot paths in this run: {len(touched_paths)}",
            ]
        )

    output.write("\n".join(lines) + "\n")
    output.flush()


def _prune_orphan_files(
    storage: FileStorageBackend,
    *,
    snapshot_dir: Path,
    orphan_paths: list[Path],
    output,
) -> int:
    lines = [
        "\n=== Snapshot Prune ===",
        "This prune is based only on snapshot paths touched in the current pytest run.",
        "Partial, filtered, or skipped runs can remove valid snapshots.",
        "",
    ]

    if not orphan_paths:
        lines.append("No orphaned snapshot files found.")
        output.write("\n".join(lines) + "\n")
        output.flush()
        return 0

    for path in orphan_paths:
        storage.delete_file(path)
        lines.append(f"Deleted: {path.relative_to(snapshot_dir)}")

    lines.extend(
        [
            "",
            f"Deleted {len(orphan_paths)} orphaned snapshot(s).",
        ]
    )
    output.write("\n".join(lines) + "\n")
    output.flush()
    return len(orphan_paths)
