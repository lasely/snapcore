"""Built-in sanitizer profile loader.

Maps profile names to pre-configured sanitizer chains so teams
can enable common sanitization without writing custom fixtures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..protocols import Sanitizer


def load_profile_sanitizers(profile: str) -> list[Sanitizer]:
    """Return the sanitizer chain for the given profile name.

    Profiles:
        ``"none"``        -- empty chain (default).
        ``"standard"``    -- flat replacement: UUIDs, datetimes, paths.
        ``"relational"``  -- identity-preserving numbered placeholders.
    """
    if profile == "none":
        return []

    if profile == "standard":
        from .builtins import UuidSanitizer, DatetimeSanitizer, PathSanitizer

        return [UuidSanitizer(), DatetimeSanitizer(), PathSanitizer()]

    if profile == "relational":
        from .relational import (
            RelationalUuidSanitizer,
            RelationalDatetimeSanitizer,
            RelationalPathSanitizer,
        )

        return [
            RelationalUuidSanitizer(),
            RelationalDatetimeSanitizer(),
            RelationalPathSanitizer(),
        ]

    raise ValueError(f"Unknown sanitizer profile: {profile!r}")
