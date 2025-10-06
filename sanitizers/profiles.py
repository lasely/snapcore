"""Built-in sanitizer profile loader.

Maps profile names to pre-configured sanitizer chains so teams
can enable common sanitization without writing custom fixtures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .builtins import DatetimeSanitizer, PathSanitizer, UuidSanitizer
from .relational import (
    RelationalDatetimeSanitizer,
    RelationalPathSanitizer,
    RelationalUuidSanitizer,
)

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
        return [UuidSanitizer(), DatetimeSanitizer(), PathSanitizer()]

    if profile == "relational":
        return [
            RelationalUuidSanitizer(),
            RelationalDatetimeSanitizer(),
            RelationalPathSanitizer(),
        ]

    raise ValueError(f"Unknown sanitizer profile: {profile!r}")
