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

    def apply_with_diagnostics(self, text: str) -> tuple[str, list[str]]:
        """Apply sanitizers and return the resulting text plus sanitizer names."""
        applied: list[str] = []
        for sanitizer in self._chain:
            text = sanitizer.sanitize(text)
            applied.append(sanitizer.name)
        return text, applied

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
