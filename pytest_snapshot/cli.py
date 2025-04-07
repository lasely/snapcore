from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

from .storage import FileStorageBackend, NamingPolicy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pytest-snapshot",
        description="Snapshot testing management CLI",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="__snapshots__",
        help="Snapshot storage directory (default: __snapshots__)",
    )

    subparsers = parser.add_subparsers(dest="command")

    clean_parser = subparsers.add_parser("clean", help="Remove orphaned snapshots")
    clean_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete orphaned files (dry-run by default)",
    )

    list_parser = subparsers.add_parser("list", help="List all snapshots")
    list_parser.add_argument("--module", default=None, help="Filter by module path prefix")
    list_parser.add_argument("--match", default=None, help="Filter by filename glob pattern")

    inspect_parser = subparsers.add_parser("inspect", help="View snapshot content")
    inspect_parser.add_argument("path", help="Path to snapshot file")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    snapshot_dir = Path(args.snapshot_dir).resolve()

    if args.command == "list":
        return _cmd_list(snapshot_dir, module=args.module, match=args.match)
    elif args.command == "inspect":
        return _cmd_inspect(Path(args.path))
    elif args.command == "clean":
        return _cmd_clean(snapshot_dir, apply=args.apply)

    return 1


def _path_contains_parts(rel_path: Path, parts: list[str]) -> bool:
    """Check if a relative path starts with the given module parts."""
    path_parts = rel_path.parts
    return path_parts[:len(parts)] == tuple(parts)


def _cmd_list(snapshot_dir: Path, *, module: str | None, match: str | None) -> int:
    backend = FileStorageBackend(NamingPolicy(), snapshot_dir)
    files = backend.list_files()

    if not files:
        print(f"No snapshots found in {snapshot_dir}")
        return 0

    filtered = files
    if module:
        module_parts = module.split(".")
        filtered = [
            f for f in filtered
            if _path_contains_parts(f.relative_to(snapshot_dir), module_parts)
        ]

    if match:
        filtered = [f for f in filtered if fnmatch.fnmatch(f.name, match)]

    if not filtered:
        print(f"No snapshots matching the given filters")
        return 0

    for f in filtered:
        rel = f.relative_to(snapshot_dir)
        size = f.stat().st_size
        size_str = _format_size(size)
        print(f"{rel}  ({size_str})")

    print(f"\nTotal: {len(filtered)} snapshot(s)")
    return 0


def _cmd_inspect(path: Path) -> int:
    if not path.exists():
        print(f"Error: Snapshot file not found: {path}", file=sys.stderr)
        return 1

    content = path.read_text(encoding="utf-8")
    print(content, end="")
    return 0


def _cmd_clean(snapshot_dir: Path, *, apply: bool) -> int:
    backend = FileStorageBackend(NamingPolicy(), snapshot_dir)
    files = backend.list_files()

    if not files:
        print(f"No snapshots found in {snapshot_dir}")
        return 0

    try:
        collected_dirs = _collect_test_dirs(snapshot_dir)
    except _PytestUnavailable:
        print(
            "Error: pytest is required for orphan detection.\n"
            f"Install pytest or manually delete files from {snapshot_dir}/.",
            file=sys.stderr,
        )
        return 1

    orphans = []
    for f in files:
        rel_parent = str(f.parent.relative_to(snapshot_dir))
        if not any(rel_parent.startswith(d) for d in collected_dirs):
            orphans.append(f)

    if not orphans:
        print("No orphaned snapshots found.")
        return 0

    for f in orphans:
        rel = f.relative_to(snapshot_dir)
        if apply:
            f.unlink()
            print(f"Deleted: {rel}")
            _cleanup_empty_parents(f.parent, snapshot_dir)
        else:
            print(f"Orphan: {rel}")

    if apply:
        print(f"\nDeleted {len(orphans)} orphaned snapshot(s).")
        return 0
    else:
        print(f"\nFound {len(orphans)} orphaned snapshot(s). Run with --apply to delete.")
        return 2


class _PytestUnavailable(Exception):
    pass


def _collect_test_dirs(snapshot_dir: Path) -> set[str]:
    """Collect test directory paths by running pytest --collect-only."""
    try:
        import pytest as _pytest
    except ImportError:
        raise _PytestUnavailable()

    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header"],
        capture_output=True,
        text=True,
    )

    dirs: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if "::" in line and not line.startswith("="):
            parts = line.split("::")
            if parts:
                module_file = parts[0].replace("\\", "/")
                if module_file.endswith(".py"):
                    module_file = module_file[:-3]
                module_parts = module_file.replace("/", "/")

                dir_parts = [module_parts]
                if len(parts) > 2:
                    dir_parts.append(parts[0] + "/" + parts[1])
                    dir_parts.append(parts[0] + "/" + parts[1] + "/" + parts[2].split("[")[0])
                elif len(parts) > 1:
                    dir_parts.append(module_parts + "/" + parts[1].split("[")[0])

                for d in dir_parts:
                    dirs.add(d.replace("\\", "/"))

    return dirs


def _cleanup_empty_parents(directory: Path, stop_at: Path) -> None:
    """Remove empty parent directories up to (but not including) stop_at."""
    current = directory
    while current != stop_at and current.exists():
        try:
            if any(current.iterdir()):
                break
            current.rmdir()
            current = current.parent
        except OSError:
            break


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"


if __name__ == "__main__":
    sys.exit(main())
