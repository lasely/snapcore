"""Root conftest: register the project root as the ``pytest_snapshot`` package.

Files live at the repository root (flat layout) but must be importable as
``pytest_snapshot.*`` so that relative imports (``from ..models``) inside
sub-packages resolve correctly.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_ROOT = str(Path(__file__).parent)


def _register_package() -> None:
    if "pytest_snapshot" in sys.modules:
        return

    spec = importlib.util.spec_from_file_location(
        "pytest_snapshot",
        Path(_ROOT) / "__init__.py",
        submodule_search_locations=[_ROOT],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "pytest_snapshot"
    sys.modules["pytest_snapshot"] = mod
    spec.loader.exec_module(mod)


_register_package()
