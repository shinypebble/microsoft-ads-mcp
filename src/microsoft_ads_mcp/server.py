"""FastMCP server: builds the instance, manages the shared client, registers tools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.transforms.search import BM25SearchTransform

from .api.client import MsAdsClient, set_client
from .config import Settings, get_settings
from .tools import register_all

# When TOOL_SEARCH is on, these orientation/onboarding tools stay directly listed; the rest are
# discovered via `search_tools`. Keep this small — it's the "you are here" set, not a catalog.
_PINNED_TOOLS = [
    "account_health",
    "search_accounts",
    "get_campaigns",
    "run_performance_report",
    "get_auth_url",
    "complete_auth",
]

_TOOL_SEARCH_NOTE = (
    "\nThis server uses tool search: only a few orientation tools are listed directly. Discover "
    "the rest with `search_tools(query)` (BM25 over names/descriptions/params) and invoke any "
    "discovered tool with `call_tool(name, arguments)`. Hidden tools keep their full typed "
    "schemas and the READ_ONLY gate."
)

_INSTRUCTIONS = (
    "Manage and report on a single Microsoft Advertising (Bing Ads) account.\n"
    "Call `account_health` first to confirm credentials and whether writes are enabled; its "
    "`auth_state` / `needs_interactive_auth` fields tell you deterministically whether to "
    "sign in. Use `search_accounts` to find account ids (and `set_active_account` to switch), "
    "then `get_campaigns` / `get_ad_groups` / `get_keywords` / `get_ads` to walk the tree. "
    "`get_ads` returns the RSA copy (headlines/descriptions/paths). `get_ads` / `get_keywords` "
    "also report `editorial_status` (the ad-review state -- Active / Inactive / ActiveLimited / "
    "Disapproved -- separate from the Active/Paused `status`), so you can tell whether an Active "
    "entity is actually approved to serve; check it first when diagnosing zero impressions. "
    "Every level reports its "
    "URL tracking (`tracking_url_template`, `final_url_suffix`, `url_custom_parameters`), but a "
    "null template there usually just means it inherits the account default -- call "
    "`get_account_url_options` for the account-level template / Final URL suffix and the "
    "`msclkid_auto_tagging_enabled` flag (the Microsoft Click ID that drives attribution). Confirm "
    "those before activating paused campaigns. `run_performance_report` "
    "downloads and parses the report for you (supports custom start/end dates and a single "
    "campaign/ad group filter). For keyword research (the Ad Insight / Keyword Planner side, all "
    "read-only and available even in READ_ONLY mode): `estimate_keyword_bids` returns the "
    "estimated first-page/mainline bid per keyword, `get_keyword_ideas` discovers keywords from "
    "seed phrases or a URL with monthly search volume and competition, and "
    "`get_keyword_traffic_estimates` projects weekly clicks/impressions/cost for a keyword at a "
    "given bid, and `check_first_page_bids` flags an ad group's keywords whose current bid is "
    'below their estimated first-page bid (the UI\'s "Below first page bid" state) -- it reads '
    "the live keyword bids and joins them to the estimate, so reach for it when diagnosing low "
    "impressions or before activating a campaign.\n"
    "When writes are enabled (READ_ONLY=false): create campaigns/ad groups/ads (created PAUSED) "
    "and edit them in place with the `update_*` tools (rename, repoint Final URLs, tracking "
    "templates / Final URL suffix / URL custom parameters, status, bids) or remove them with "
    "`delete_*`. `set_account_url_options` sets the tracking template / suffix / msclkid "
    "auto-tagging once for the whole account (cleaner than editing every campaign). Also "
    "available: negative keywords "
    "(`add_negative_keywords` / `get_negative_keywords` / `remove_negative_keywords`), ad "
    "extensions (`get_ad_extensions`, `add_call_extension`, `update_call_extension`, "
    "`add_callout_extension`, `add_sitelink_extension`, `delete_ad_extension`), conversion "
    "goals and UET tags (`get_conversion_goals` reports `exclude_from_bidding` -- the inverse of "
    "the 'Include in conversions' checkbox that decides whether a goal feeds automated bidding -- "
    "and `update_conversion_goal` sets it plus status / name / count type / window / revenue; "
    "`get_uet_tags` / `update_uet_tag`), ZIP/location targeting "
    "(`resolve_postal_codes` then `add_location_targets` / `get_location_targets` / "
    "`remove_location_targets`, plus `get_location_intent` / `set_location_intent` for "
    "presence vs. search-interest targeting), ad scheduling / dayparting "
    "(`get_ad_schedules` / `add_ad_schedules` / `remove_ad_schedules`; times run in the "
    "campaign time zone, settable via `update_campaign`), device bid adjustments "
    "(`get_device_bid_adjustments` / `set_device_bid_adjustment`; Microsoft calls mobile "
    '"Smartphones"), and the Bulk API (`bulk_download` / `bulk_upload`).\n'
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

    instructions = _INSTRUCTIONS + (_TOOL_SEARCH_NOTE if settings.tool_search else "")
    mcp: FastMCP = FastMCP(name="microsoft-ads", instructions=instructions, lifespan=lifespan)
    register_all(mcp, settings)

    if settings.tool_search:
        # Collapse the catalog behind BM25 search_tools / call_tool, keeping the pinned
        # orientation tools listed. (All pins are read/auth tools, so they're always registered
        # regardless of READ_ONLY; keep it that way — a write-tool pin would vanish in read-only.)
        mcp.add_transform(BM25SearchTransform(always_visible=_PINNED_TOOLS))

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
