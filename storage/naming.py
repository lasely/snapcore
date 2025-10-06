"""Filesystem naming policy for logical snapshot keys.

The module converts snapshot identities into deterministic file paths while
applying a minimal normalization policy for characters that are unsafe on
common operating systems.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import SnapshotKey

_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|]')


class NamingPolicy:
    """Resolve logical snapshot keys into stable filesystem paths."""

    def resolve(self, key: SnapshotKey, base_dir: Path) -> Path:
        """Resolve ``key`` below ``base_dir`` and return an absolute target path."""
        parts: list[str] = []
        parts.extend(key.module.split("."))

        if key.class_name is not None:
            parts.append(self._safe(key.class_name))

        parts.append(self._safe(key.test_name))
        filename = self._safe(key.snapshot_name) + ".txt"

        path = base_dir
        for part in parts:
            path = path / part
        path = path / filename

        return path.resolve()

    @staticmethod
    def _safe(name: str) -> str:
        """Replace characters that are unsafe in common filesystem names."""
        return _UNSAFE_CHARS.sub("_", name)
