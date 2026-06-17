"""Error types and translation from the msads / openapi_client exception hierarchy.

The REST SDK raises typed HTTP exceptions (``openapi_client.exceptions``). We collapse those
into a small, agent-friendly hierarchy so the tool layer never has to import SDK internals.
"""

from __future__ import annotations

import json
from typing import Any

from openapi_client.exceptions import ApiException, OpenApiException


class MsAdsApiError(Exception):
    """A failed Microsoft Advertising API call, normalized for the tool layer."""

    def __init__(self, status: int, message: str, *, body: Any = None) -> None:
        self.status = status
        self.message = message
        self.body = body
        super().__init__(f"({status}) {message}" if status else message)

    def as_dict(self) -> dict[str, Any]:
        """Compact representation (no stack trace), safe to return to an agent."""
        return {"status": self.status, "message": self.message}


class InvalidCredentialsError(MsAdsApiError):
    """Auth failed: missing/invalid developer token, client id, or OAuth refresh token."""


def _message_from_body(body: Any) -> str | None:
    """Best-effort human-readable message from a REST error body (often JSON)."""
    if body is None:
        return None
    if isinstance(body, (bytes, bytearray)):
        try:
            body = body.decode("utf-8", "replace")
        except Exception:  # pragma: no cover - defensive
            return None
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return body.strip() or None
    if isinstance(body, dict):
        # Microsoft REST errors typically nest under "error" or carry an "Errors" array.
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        errors = body.get("Errors") or body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return first.get("Message") or first.get("message") or json.dumps(first)
        if isinstance(body.get("message"), str):
            return body["message"]
    return None


def translate(exc: Exception) -> MsAdsApiError:
    """Convert any SDK / transport exception into an ``MsAdsApiError``.

    Already-translated errors pass through unchanged.
    """
    if isinstance(exc, MsAdsApiError):
        return exc
    if isinstance(exc, ApiException):
        status = int(getattr(exc, "status", 0) or 0)
        body = getattr(exc, "body", None)
        message = _message_from_body(body) or getattr(exc, "reason", None) or str(exc)
        if status in (401, 403):
            return InvalidCredentialsError(status, message, body=body)
        return MsAdsApiError(status, message, body=body)
    if isinstance(exc, OpenApiException):
        return MsAdsApiError(0, str(exc) or exc.__class__.__name__)
    # OAuth token failures and anything else transport-level.
    name = exc.__class__.__name__
    if "OAuth" in name or "Token" in name:
        return InvalidCredentialsError(0, str(exc) or name)
    return MsAdsApiError(0, str(exc) or name)
