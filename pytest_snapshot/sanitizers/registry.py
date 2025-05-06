from __future__ import annotations

from ..protocols import Sanitizer


class SanitizerRegistry:
    """Ordered chain of sanitizers applied sequentially."""

    def __init__(self) -> None:
        self._chain: list[Sanitizer] = []
        self._by_name: dict[str, Sanitizer] = {}

    def register(self, sanitizer: Sanitizer) -> None:
        """Append a sanitizer to the chain.

        Sanitizers are applied in registration order.
        """
        if sanitizer.name in self._by_name:
            raise ValueError(f"Sanitizer with name '{sanitizer.name}' already registered")
        self._chain.append(sanitizer)
        self._by_name[sanitizer.name] = sanitizer

    def apply(self, text: str) -> str:
        """Apply all registered sanitizers sequentially.

        Each sanitizer receives the output of the previous one.
        Returns text unchanged if no sanitizers are registered.
        """
        return self.apply_with_diagnostics(text)[0]

    def apply_with_diagnostics(
        self, text: str,
    ) -> tuple[str, list[str], dict[str, int]]:
        """Apply sanitizers and return text, names, and per-sanitizer replacement counts."""
        applied: list[str] = []
        counts: dict[str, int] = {}
        for sanitizer in self._chain:
            before = text
            text = sanitizer.sanitize(text)
            applied.append(sanitizer.name)
            counts[sanitizer.name] = 0 if text == before else _count_changes(before, text)
        return text, applied, counts

    def reset_stateful(self) -> None:
        """Reset all stateful sanitizers (those with a reset() method).

        Called before each apply() to ensure independent numbering per snapshot.
        """
        for sanitizer in self._chain:
            if hasattr(sanitizer, "reset"):
                sanitizer.reset()

    def unregister(self, name: str) -> None:
        """Remove a sanitizer by name. No-op if not found."""
        if name in self._by_name:
            del self._by_name[name]
        self._chain = [s for s in self._chain if s.name != name]

    def list(self) -> list[str]:
        """Return sanitizer names in application order."""
        return [s.name for s in self._chain]


def _count_changes(before: str, after: str) -> int:
    """Estimate the number of replacements made by a sanitizer.

    Uses difflib SequenceMatcher to count contiguous changed regions,
    which closely approximates per-replacement counts.
    """
    import difflib

    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return sum(1 for tag, *_ in matcher.get_opcodes() if tag != "equal")
