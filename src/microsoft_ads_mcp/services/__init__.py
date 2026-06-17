"""Service flows: map agent intents onto the Microsoft Advertising API's request shapes."""

from __future__ import annotations

from typing import Any


def as_list(value: Any) -> list[Any]:
    """Normalize a REST list field that may be ``None`` or a bare item into a list.

    The REST SDK returns plain Python lists for collections, but some responses use ``None``
    for "empty"; this keeps call sites tidy.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def first_attr(obj: Any, *names: str, default: Any = None) -> Any:
    """Return the first present attribute among ``names`` (Pascal/snake tolerant)."""
    for name in names:
        val = getattr(obj, name, None)
        if val is not None:
            return val
    return default
