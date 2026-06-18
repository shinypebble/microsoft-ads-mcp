"""The connection/health tool — the first call an agent should make."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..api.errors import InvalidCredentialsError, MsAdsApiError
from ..config import Settings
from ..domain.entities import AccountHealth, AuthState
from ..services import first_attr
from ..services.accounts import get_user


def _classify_auth_error(settings: Settings, exc: MsAdsApiError) -> tuple[AuthState, bool]:
    """Map an auth failure to a discriminated ``(auth_state, needs_interactive_auth)``.

    ``needs_interactive_auth`` is true only when re-running get_auth_url / complete_auth is
    actually the fix. For a present-but-rejected token it is false: re-consent could clobber a
    shared token and the real cause may be a dev-token/account binding, not a stale credential.
    """
    msg = (exc.message or "").lower()
    if not settings.developer_token:
        return "dev_token_missing", False
    if isinstance(exc, InvalidCredentialsError):
        if "no refresh token" in msg:
            return "no_token", True
        if "expired" in msg:
            return "token_expired", True
        return "token_rejected", False
    if "inactive" in msg or "not active" in msg:
        return "account_inactive", False
    return "token_rejected", False


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(tags={"read"}, annotations=ToolAnnotations(readOnlyHint=True))
    def account_health() -> AccountHealth:
        """Validate credentials and report the environment and write mode.

        Call this first. ``read_only`` tells you whether write tools are available this
        session; ``environment`` is production or sandbox. ``auth_state`` discriminates *why*
        auth failed (e.g. no_token vs token_rejected); branch on ``needs_interactive_auth``
        rather than the message string.
        """
        client = get_client()
        try:
            user = get_user(client)
        except MsAdsApiError as exc:
            auth_state, needs_auth = _classify_auth_error(settings, exc)
            return AccountHealth(
                ok=False,
                auth_state=auth_state,
                needs_interactive_auth=needs_auth,
                read_only=settings.read_only,
                environment=settings.environment,
                message=f"Authentication failed: {exc.message}",
            )
        return AccountHealth(
            ok=True,
            auth_state="ok",
            needs_interactive_auth=False,
            read_only=settings.read_only,
            environment=settings.environment,
            user_name=first_attr(user, "UserName", "user_name"),
            account_id=str(client.account_id) if client.account_id else None,
            customer_id=str(settings.customer_id) or None,
            message="Connected." + (" Read-only mode." if settings.read_only else ""),
        )
