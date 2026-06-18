"""The core safety guarantee: write tools do not exist when READ_ONLY is on."""

from __future__ import annotations

import asyncio

from microsoft_ads_mcp.config import Settings
from microsoft_ads_mcp.server import create_server

WRITE_TOOLS = {
    "create_campaign",
    "update_campaign_status",
    "update_campaign",
    "create_ad_group",
    "update_ad_group",
    "add_keywords",
    "update_keyword",
    "create_responsive_search_ad",
    "update_responsive_search_ad",
    "delete_campaign",
    "delete_ad_group",
    "delete_ad",
    "delete_keyword",
    "add_negative_keywords",
    "remove_negative_keywords",
    "update_call_extension",
    "add_callout_extension",
    "add_sitelink_extension",
    "update_conversion_goal",
    "update_uet_tag",
    "add_location_targets",
    "remove_location_targets",
    "bulk_upload",
}
READ_TOOLS = {
    "account_health",
    "search_accounts",
    "get_campaigns",
    "get_ad_groups",
    "get_keywords",
    "get_ads",
    "get_budgets",
    "get_negative_keywords",
    "get_ad_extensions",
    "get_conversion_goals",
    "get_uet_tags",
    "set_active_account",
    "get_location_targets",
    "resolve_postal_codes",
    "bulk_download",
    "run_performance_report",
}


def _tool_names(settings: Settings) -> set[str]:
    server = create_server(settings)
    tools = asyncio.run(server.list_tools())
    return {t.name for t in tools}


def test_write_tools_absent_when_read_only(readonly_settings: Settings) -> None:
    names = _tool_names(readonly_settings)
    assert names & WRITE_TOOLS == set()
    assert names >= READ_TOOLS  # read tools are always present


def test_write_tools_present_when_writable(writable_settings: Settings) -> None:
    names = _tool_names(writable_settings)
    assert names >= WRITE_TOOLS
    assert names >= READ_TOOLS


def test_write_tools_tagged_write(writable_settings: Settings) -> None:
    server = create_server(writable_settings)
    tools = asyncio.run(server.list_tools())
    write_tagged = {t.name for t in tools if "write" in (t.tags or set())}
    assert write_tagged >= WRITE_TOOLS
