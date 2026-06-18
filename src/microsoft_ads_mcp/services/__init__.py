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


def _err_msg(err: Any) -> str:
    """Render one ``BatchError``-like object as ``"<code>: <message>"``."""
    msg = first_attr(err, "Message", "message", default="")
    code = first_attr(err, "ErrorCode", "error_code", "Code", "code", default="")
    return f"{code}: {msg}".strip(": ")


def flat_partial_errors(resp: Any) -> list[str]:
    """Flatten a flat ``PartialErrors`` list (of BatchError) into messages."""
    return [_err_msg(e) for e in as_list(first_attr(resp, "PartialErrors", "partial_errors"))]


def nested_partial_errors(resp: Any) -> list[str]:
    """Flatten ``NestedPartialErrors`` (a list of BatchErrorCollection) into messages.

    Microsoft returns nested errors for batch operations that group items per entity
    (negative keywords, ad extensions): each collection is one entity, carrying its own
    ``BatchErrors`` (and sometimes a collection-level error with no nested batch).
    """
    out: list[str] = []
    for coll in as_list(first_attr(resp, "NestedPartialErrors", "nested_partial_errors")):
        errs = as_list(first_attr(coll, "BatchErrors", "batch_errors"))
        if not errs and coll is not None:
            errs = [coll]
        out.extend(_err_msg(e) for e in errs)
    return out
