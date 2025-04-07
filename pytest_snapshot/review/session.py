"""Interactive approval workflow for pending snapshot changes.

The session presents one collected change at a time and defers writes until
the decision loop completes, preserving an all-or-nothing review experience.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import IO, Callable, TYPE_CHECKING

from .collector import ChangeType, PendingChange

if TYPE_CHECKING:
    from ..protocols import StorageBackend


_SEPARATOR = "=" * 60
_THIN_SEP = "-" * 60


@dataclass(frozen=True)
class ReviewResult:
    """Result object returned by an interactive review session."""

    accepted: list[PendingChange] = field(default_factory=list)
    skipped: list[PendingChange] = field(default_factory=list)

    @property
    def has_skipped(self) -> bool:
        """Return whether any changes were skipped or left unapproved."""
        return len(self.skipped) > 0


class ReviewSession:
    """Drive interactive approval of collected snapshot changes."""

    def __init__(
        self,
        pending: list[PendingChange],
        storage: StorageBackend,
        output: IO[str] | None = None,
        input_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._pending = pending
        self._storage = storage
        self._output = output or sys.stdout
        self._input_fn = input_fn or input

    def run(self) -> ReviewResult:
        """Execute the review loop and return accepted and skipped changes."""
        if not self._pending:
            self._write("\nNo snapshot changes to review.\n")
            return ReviewResult()

        try:
            return self._run_loop()
        except KeyboardInterrupt:
            self._write("\n\nAborted. No changes written.\n")
            return ReviewResult(accepted=[], skipped=list(self._pending))
        except (OSError, EOFError) as exc:
            msg = str(exc).lower()
            if "stdin" in msg or "captured" in msg:
                self._write(
                    "\n\n[!] Cannot read from stdin -- pytest is capturing it.\n"
                    "    Re-run with -s to enable interactive review:\n\n"
                    "        pytest -s --snapshot-review\n\n"
                    "    All changes skipped (nothing written).\n"
                )
            else:
                self._write(
                    f"\n\n[!] stdin closed or not available ({exc}).\n"
                    "    All changes skipped (nothing written).\n"
                )
            return ReviewResult(accepted=[], skipped=list(self._pending))

    def _run_loop(self) -> ReviewResult:
        total = len(self._pending)
        accepted: list[PendingChange] = []
        skipped: list[PendingChange] = []

        self._write(f"\n{_SEPARATOR}\n")
        self._write(f"  Snapshot Review -- {total} change(s) to review\n")
        self._write(f"{_SEPARATOR}\n")

        for idx, change in enumerate(self._pending):
            self._print_change(change, idx + 1, total)
            action = self._prompt()

            if action == "a":
                accepted.append(change)
            elif action == "s":
                skipped.append(change)
            elif action == "A":
                accepted.append(change)
                accepted.extend(self._pending[idx + 1:])
                break
            elif action == "q":
                skipped.append(change)
                skipped.extend(self._pending[idx + 1:])
                break

        for change in accepted:
            self._storage.write(change.key, change.actual)

        self._write(f"\n{_SEPARATOR}\n")
        self._write("  Review complete:\n")
        self._write(f"    [+]  {len(accepted)} accepted\n")
        self._write(f"    [-]  {len(skipped)} skipped\n")
        self._write(f"{_SEPARATOR}\n")

        return ReviewResult(accepted=accepted, skipped=skipped)

    def _print_change(self, change: PendingChange, index: int, total: int) -> None:
        """Render one pending change before prompting for an action."""
        key = change.key
        location = f"{key.module}::{key.test_name}"
        if key.class_name:
            location = f"{key.module}::{key.class_name}::{key.test_name}"

        self._write(f"\n{_THIN_SEP}\n")
        self._write(f"  [{index}/{total}] {location}\n")
        self._write(f"  Snapshot: \"{key.snapshot_name}\"")
        if change.diagnostics is not None and change.diagnostics.snapshot_path is not None:
            self._write(f"\n  Path: {change.diagnostics.snapshot_path}")
        if change.diagnostics is not None:
            self._write(f"\n  Serializer: {change.diagnostics.serializer_name}")
            if change.diagnostics.repr_fallback_used:
                self._write(" (repr fallback)")
            sanitizers = ", ".join(change.diagnostics.sanitizer_names) or "none"
            self._write(f"\n  Sanitizers: {sanitizers}")
            if change.diagnostics.diff_fallback_reason is not None:
                self._write(f"\n  Diff fallback: {change.diagnostics.diff_fallback_reason}")
        self._write("\n")

        if change.change_type == ChangeType.CREATED:
            lines = change.actual.count("\n") + 1
            self._write(f"  (NEW -- {lines} lines)\n\n")
            for line in change.actual.splitlines():
                self._write(f"  + {line}\n")
        else:
            self._write("\n")
            for line in change.diff.splitlines():
                self._write(f"  {line}\n")

    def _prompt(self) -> str:
        """Prompt until the user enters a supported review command."""
        valid = {"a", "s", "A", "q"}
        while True:
            self._write("\n  [a]ccept  [s]kip  [A]ccept all  [q]uit\n")
            answer = self._input_fn("  > ").strip()
            if answer in valid:
                return answer
            self._write(f"  Unknown command: {answer!r}. Use a/s/A/q.\n")

    def _write(self, text: str) -> None:
        """Write text to the configured output stream with encoding fallback."""
        try:
            self._output.write(text)
            self._output.flush()
        except UnicodeEncodeError:
            enc = getattr(self._output, "encoding", "ascii") or "ascii"
            safe = text.encode(enc, errors="replace").decode(enc)
            self._output.write(safe)
            self._output.flush()
