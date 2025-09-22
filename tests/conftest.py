"""Shared fixtures for pytest-snapshot integration tests."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]


@pytest.fixture
def run_snapshot(pytester):
    """Run pytester with the snapshot plugin loaded."""

    def _run(*extra_args: str):
        args = ["-p", "pytest_snapshot.plugin", "-p", "no:syrupy", *extra_args]
        return pytester.runpytest(*args)

    return _run
