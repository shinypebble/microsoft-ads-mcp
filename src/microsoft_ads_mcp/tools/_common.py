"""Shared helpers for the tool layer: error translation into clean ToolErrors."""

from __future__ import annotations

from collections.abc import Callable

from fastmcp.exceptions import ToolError

from ..api.errors import InvalidCredentialsError, MsAdsApiError


def guarded[T](fn: Callable[[], T]) -> T:
    """Run ``fn``, converting API/validation errors into clean ``ToolError`` messages.

    The tools are synchronous (the SDK is sync); FastMCP runs them in a worker thread.
    """
    try:
        return fn()
    except InvalidCredentialsError as exc:
        raise ToolError(f"Authentication failed: {exc.message}") from exc
    except MsAdsApiError as exc:
        raise ToolError(exc.message) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
