"""The connection/health tool — the first call an agent should make."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..api.errors import MsAdsApiError
from ..config import Settings
from ..domain.entities import AccountHealth
from ..services import first_attr
from ..services.accounts import get_user


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(tags={"read"}, annotations=ToolAnnotations(readOnlyHint=True))
    def account_health() -> AccountHealth:
        """Validate credentials and report the environment and write mode.

        Call this first. ``read_only`` tells you whether write tools are available this
        session; ``environment`` is production or sandbox.
        """
        client = get_client()
        try:
            user = get_user(client)
        except MsAdsApiError as exc:
            return AccountHealth(
                ok=False,
                read_only=settings.read_only,
                environment=settings.environment,
                message=f"Authentication failed: {exc.message}",
            )
        return AccountHealth(
            ok=True,
            read_only=settings.read_only,
            environment=settings.environment,
            user_name=first_attr(user, "UserName", "user_name"),
            account_id=str(client.account_id) if client.account_id else None,
            customer_id=str(settings.customer_id) or None,
            message="Connected." + (" Read-only mode." if settings.read_only else ""),
        )
