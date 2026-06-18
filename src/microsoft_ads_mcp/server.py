"""FastMCP server: builds the instance, manages the shared client, registers tools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP

from .api.client import MsAdsClient, set_client
from .config import Settings, get_settings
from .tools import register_all

_INSTRUCTIONS = (
    "Manage and report on a single Microsoft Advertising (Bing Ads) account.\n"
    "Call `account_health` first to confirm credentials and whether writes are enabled; its "
    "`auth_state` / `needs_interactive_auth` fields tell you deterministically whether to "
    "sign in. Use `search_accounts` to find account ids (and `set_active_account` to switch), "
    "then `get_campaigns` / `get_ad_groups` / `get_keywords` / `get_ads` to walk the tree. "
    "`get_ads` returns the RSA copy (headlines/descriptions/paths). `run_performance_report` "
    "downloads and parses the report for you (supports custom start/end dates and a single "
    "campaign/ad group filter).\n"
    "When writes are enabled (READ_ONLY=false): create campaigns/ad groups/ads (created PAUSED) "
    "and edit them in place with the `update_*` tools (rename, repoint Final URLs, tracking "
    "templates, status, bids) or remove them with `delete_*`. Also available: negative keywords "
    "(`add_negative_keywords` / `get_negative_keywords` / `remove_negative_keywords`), ad "
    "extensions (`get_ad_extensions`, `update_call_extension`, `add_callout_extension`, "
    "`add_sitelink_extension`), conversion goals and UET tags (`get_conversion_goals` / "
    "`update_conversion_goal`, `get_uet_tags` / `update_uet_tag`), ZIP/location targeting "
    "(`resolve_postal_codes` then `add_location_targets` / `get_location_targets` / "
    "`remove_location_targets`), and the Bulk API (`bulk_download` / `bulk_upload`).\n"
    "First-time sign-in: if a tool reports authentication failed / no refresh token, the user "
    "must authorize once. Call `get_auth_url`, present the returned URL to the user as a "
    "sign-in link, and ask them to sign in with the account that manages the ad account "
    "(Microsoft, or Google for Google-federated accounts). They will land on a near-blank "
    "page; have them paste that full redirect URL "
    "back, then call `complete_auth` with it. This is only needed once."
)


def _skills_root() -> Path | None:
    """Locate the bundled ``skill/`` directory across dev and installed layouts."""
    here = Path(__file__).resolve()
    candidates = (
        here.parent / "skill",  # installed wheel: microsoft_ads_mcp/skill/
        here.parents[2] / "skill",  # source checkout: <repo>/skill/
    )
    return next((p for p in candidates if p.is_dir()), None)


def create_server(settings: Settings | None = None) -> FastMCP:
    """Construct a fully-registered server. Write tools are gated by ``settings.read_only``."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict]:
        if not settings.has_credentials:
            raise RuntimeError(
                "MICROSOFT_ADS_DEVELOPER_TOKEN and MICROSOFT_ADS_CLIENT_ID must be set."
            )
        client = MsAdsClient(settings)
        set_client(client)
        try:
            yield {}
        finally:
            set_client(None)

    mcp: FastMCP = FastMCP(name="microsoft-ads", instructions=_INSTRUCTIONS, lifespan=lifespan)
    register_all(mcp, settings)

    skills_root = _skills_root()
    if skills_root is not None:
        try:
            from fastmcp.server.providers.skills import SkillsDirectoryProvider

            mcp.add_provider(SkillsDirectoryProvider(roots=skills_root))
        except Exception:
            pass

    return mcp


# Module-level instance for `fastmcp run src/microsoft_ads_mcp/server.py:mcp`.
mcp = create_server()
