"""File-backed snapshot persistence utilities.

The backend is intentionally strict: it resolves paths through the naming
policy, detects normalized-name collisions, writes atomically, and rejects
resolved paths that would escape the configured snapshot directory.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..exceptions import StorageError
from ..models import SnapshotKey
from .naming import NamingPolicy


class FileStorageBackend:
    """Persist snapshots as UTF-8 text files below a single base directory."""

    def __init__(self, naming: NamingPolicy, base_dir: Path) -> None:
        self._naming = naming
        self._base_dir = base_dir.resolve()
        self._resolved_keys: dict[Path, SnapshotKey] = {}

    def path_for(self, key: SnapshotKey) -> Path:
        """Resolve and validate the target path for ``key``."""
        path = self._ensure_under_base_dir(self._naming.resolve(key, self._base_dir), key=key)
        existing = self._resolved_keys.get(path)
        if existing is not None and existing != key:
            raise StorageError(
                f"Naming collision: {existing!r} and {key!r} both resolve to {path}",
                key=key,
            )
        self._resolved_keys[path] = key
        return path

    def read(self, key: SnapshotKey) -> str | None:
        """Read snapshot content for ``key`` or return ``None`` when absent."""
        path = self.path_for(key)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Failed to read snapshot: {exc}", key=key) from exc

    def write(self, key: SnapshotKey, content: str) -> None:
        """Write snapshot content atomically using UTF-8 text semantics."""
        path = self.path_for(key)
        temp_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                delete=False,
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
            ) as tmp:
                tmp.write(content)
                temp_path = Path(tmp.name)
            temp_path.replace(path)
        except OSError as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise StorageError(f"Failed to write snapshot: {exc}", key=key) from exc

    def delete(self, key: SnapshotKey) -> None:
        """Delete the file for ``key`` and silently ignore missing targets."""
        self.delete_file(self.path_for(key), key=key)

    def list_files(self) -> list[Path]:
        """Return all stored snapshot files below the configured base directory."""
        if not self._base_dir.exists():
            return []
        try:
            return sorted(p.resolve() for p in self._base_dir.rglob("*.txt"))
        except OSError as exc:
            raise StorageError(f"Failed to list snapshot files: {exc}") from exc

    def orphan_files(self, active_paths: set[Path]) -> list[Path]:
        """Return stored files that were not referenced during the active run."""
        normalized_active = {
            self._ensure_under_base_dir(Path(path).resolve())
            for path in active_paths
        }
        return [path for path in self.list_files() if path not in normalized_active]

    def delete_file(self, path: Path, *, key: SnapshotKey | None = None) -> None:
        """Delete ``path`` after validation and prune empty parent directories."""
        resolved = self._ensure_under_base_dir(path.resolve(), key=key)
        try:
            resolved.unlink(missing_ok=True)
            self._resolved_keys.pop(resolved, None)
            self._cleanup_empty_parents(resolved.parent)
        except OSError as exc:
            raise StorageError(f"Failed to delete snapshot: {exc}", key=key) from exc

    def _ensure_under_base_dir(
        self,
        path: Path,
        *,
        key: SnapshotKey | None = None,
    ) -> Path:
        """Reject resolved paths that escape the configured snapshot directory."""
        try:
            path.relative_to(self._base_dir)
        except ValueError as exc:
            raise StorageError(
                f"Resolved snapshot path escapes snapshot directory: {path}",
                key=key,
            ) from exc
        return path

    def _cleanup_empty_parents(self, directory: Path) -> None:
        """Remove empty parent directories without crossing the base directory."""
        current = directory
        while current != self._base_dir and current.exists():
            try:
                if any(current.iterdir()):
                    break
                current.rmdir()
                current = current.parent
            except OSError:
                break
