"""Read tools: accounts, campaigns, ad groups, keywords, ads, budgets."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..domain.entities import (
    AccountSummary,
    AdGroupSummary,
    AdSummary,
    CampaignSummary,
    KeywordSummary,
)
from ..services import accounts, campaigns
from ._common import guarded

_READ = ToolAnnotations(readOnlyHint=True)


def register(mcp: FastMCP) -> None:
    @mcp.tool(tags={"read"}, annotations=_READ)
    def search_accounts() -> list[AccountSummary]:
        """List every Microsoft Advertising account reachable by the authenticated user."""
        return guarded(lambda: accounts.search_accounts(get_client()))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_campaigns(include_deleted: bool = False) -> list[CampaignSummary]:
        """List Search campaigns in the configured account.

        Args:
            include_deleted: Include campaigns with status Deleted (default False).
        """
        return guarded(
            lambda: campaigns.get_campaigns(get_client(), include_deleted=include_deleted)
        )

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_ad_groups(campaign_id: str) -> list[AdGroupSummary]:
        """List ad groups in a campaign.

        Args:
            campaign_id: The campaign id.
        """
        return guarded(lambda: campaigns.get_ad_groups(get_client(), campaign_id))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_keywords(ad_group_id: str) -> list[KeywordSummary]:
        """List keywords in an ad group.

        Args:
            ad_group_id: The ad group id.
        """
        return guarded(lambda: campaigns.get_keywords(get_client(), ad_group_id))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_ads(ad_group_id: str) -> list[AdSummary]:
        """List text/responsive-search ads in an ad group.

        Args:
            ad_group_id: The ad group id.
        """
        return guarded(lambda: campaigns.get_ads(get_client(), ad_group_id))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_budgets() -> list[dict[str, Any]]:
        """Per-campaign budget view (daily budget and any shared-budget id)."""
        return guarded(lambda: campaigns.get_budgets(get_client()))
