"""Change models for structural diff output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ValueChanged:
    """Value changed while retaining the same type."""

    path: str
    old_value: Any
    new_value: Any


@dataclass(frozen=True, slots=True)
class KeyAdded:
    """Key added to dict or element added to list."""

    path: str
    value: Any


@dataclass(frozen=True, slots=True)
class KeyRemoved:
    """Key removed from dict or element removed from list."""

    path: str
    value: Any


@dataclass(frozen=True, slots=True)
class TypeChanged:
    """Value type changed (e.g. str -> int)."""

    path: str
    old_value: Any
    new_value: Any


Change = ValueChanged | KeyAdded | KeyRemoved | TypeChanged
