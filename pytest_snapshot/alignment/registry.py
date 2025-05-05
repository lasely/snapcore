"""Path-based alignment rule registry.

The registry maps normalized JSON paths to alignment rules and provides
exact-match lookup.  It is the primary entry point for the diff engine
to discover which lists should be aligned by identity keys.
"""

from __future__ import annotations

from .models import AlignmentRule
from .paths import normalize_path


class AlignmentRegistry:
    """Map JSON paths to alignment rules for keyed list matching.

    The registry stores rules keyed by their normalized path and provides
    exact-match lookup.  It is constructed once per assertion via
    ``from_dict`` and is not modified afterward.

    Thread safety is not required (pytest is single-threaded per worker).
    """

    def __init__(self) -> None:
        self._rules: dict[str, AlignmentRule] = {}

    def register(self, rule: AlignmentRule) -> None:
        """Register an alignment rule.

        The rule's path is normalized before storage.  Registering a
        second rule for an already-registered path raises ``ValueError``
        to prevent accidental conflicts.
        """
        normalized = normalize_path(rule.path)
        canonical = AlignmentRule(path=normalized, fields=rule.fields)

        existing = self._rules.get(normalized)
        if existing is not None:
            raise ValueError(
                f"Alignment rule already registered for path '{normalized}': "
                f"existing fields={existing.fields}, new fields={canonical.fields}"
            )
        self._rules[normalized] = canonical

    def lookup(self, path: str) -> AlignmentRule | None:
        """Find the rule registered for a given path.

        Returns ``None`` if no rule matches.  The path is normalized
        before lookup.
        """
        return self._rules.get(normalize_path(path))

    @classmethod
    def from_dict(
        cls, match_lists_by: dict[str, str | list[str]],
    ) -> AlignmentRegistry:
        """Build a registry from the user-facing ``match_lists_by`` API.

        Normalizes string values to 1-tuples and list values to tuples.
        This is the primary construction path invoked by the facade.

        Example::

            AlignmentRegistry.from_dict({
                "$.users": "id",
                "$.orders": ["region", "number"],
            })
        """
        registry = cls()
        for path, fields in match_lists_by.items():
            if isinstance(fields, str):
                fields_tuple = (fields,)
            elif isinstance(fields, (list, tuple)):
                fields_tuple = tuple(fields)
            else:
                raise TypeError(
                    f"match_lists_by values must be str or list[str], "
                    f"got {type(fields).__name__} for path '{path}'"
                )
            registry.register(AlignmentRule(path=path, fields=fields_tuple))
        return registry

    def rules(self) -> list[AlignmentRule]:
        """Return all registered rules for diagnostics."""
        return list(self._rules.values())

    def __len__(self) -> int:
        return len(self._rules)

    def __bool__(self) -> bool:
        return len(self) > 0

    def __contains__(self, path: str) -> bool:
        return normalize_path(path) in self._rules
