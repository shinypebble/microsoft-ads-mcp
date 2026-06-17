"""Interactive OAuth tools: mint and persist a refresh token when none is configured."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api import auth
from ..config import Settings
from ._common import guarded


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    def get_auth_url() -> str:
        """Return the OAuth sign-in URL. Open it, sign in, then call complete_auth.

        Only needed once if MICROSOFT_ADS_REFRESH_TOKEN is not set.
        """
        return guarded(lambda: auth.authorization_url(settings))

    @mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
    def complete_auth(redirect_url: str) -> str:
        """Complete OAuth using the full redirect URL from the browser, persisting the token.

        Args:
            redirect_url: The URL the browser landed on after sign-in (contains ``code=``).
        """

        def _run() -> str:
            auth.complete_authorization(settings, redirect_url)
            return "Authentication successful. Refresh token saved; future calls auto-refresh."

        return guarded(_run)
