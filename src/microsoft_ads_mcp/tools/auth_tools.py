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
        """Begin one-time sign-in: returns an OAuth sign-in URL to give the user.

        The URL targets the account's identity provider (Microsoft by default, or Google for
        Google-federated accounts). Present it to the user as a clickable sign-in link, and ask
        them to sign in with the account that manages the ad account. After they sign in,
        the browser lands on a near-blank page whose address-bar URL contains a ``code=``
        value; have them paste that full URL back, then call ``complete_auth`` with it.

        Only needed once, when no refresh token is configured. The minted token is persisted
        and auto-refreshed thereafter, so the user never has to repeat this.
        """
        return guarded(lambda: auth.authorization_url(settings))

    @mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
    def complete_auth(redirect_url: str) -> str:
        """Finish sign-in: exchange the browser's redirect URL for a saved refresh token.

        Call this with the URL the user pasted back after completing ``get_auth_url``.

        Args:
            redirect_url: The full URL the browser landed on after sign-in (contains ``code=``).
        """

        def _run() -> str:
            auth.complete_authorization(settings, redirect_url)
            return "Authentication successful. Refresh token saved; future calls auto-refresh."

        return guarded(_run)
