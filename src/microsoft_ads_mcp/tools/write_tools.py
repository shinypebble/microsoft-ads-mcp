"""Write tools — registered only when READ_ONLY is false. New entities are created paused."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..domain.entities import MatchType, MutationResult
from ..services import mutations
from ._common import guarded

_WRITE = ToolAnnotations(readOnlyHint=False)


def register(mcp: FastMCP) -> None:
    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def create_campaign(name: str, daily_budget: float, description: str = "") -> MutationResult:
        """Create a Search campaign (PAUSED by default for safety).

        Args:
            name: Campaign name.
            daily_budget: Daily budget in account currency.
            description: Optional description.
        """
        return guarded(
            lambda: mutations.create_campaign(
                get_client(), name=name, daily_budget=daily_budget, description=description
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def update_campaign_status(campaign_id: str, status: str) -> MutationResult:
        """Set a campaign Active or Paused.

        Args:
            campaign_id: The campaign id.
            status: "Active" or "Paused".
        """
        return guarded(
            lambda: mutations.update_campaign_status(
                get_client(), campaign_id=campaign_id, status=status
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def create_ad_group(
        campaign_id: str, name: str, cpc_bid: float = 1.0, language: str = "English"
    ) -> MutationResult:
        """Create an ad group (PAUSED) in a campaign.

        Args:
            campaign_id: The parent campaign id.
            name: Ad group name.
            cpc_bid: Default CPC bid in account currency (default 1.0).
            language: Ad group language (required by Microsoft; default "English").
        """
        return guarded(
            lambda: mutations.create_ad_group(
                get_client(), campaign_id=campaign_id, name=name, cpc_bid=cpc_bid, language=language
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def add_keywords(
        ad_group_id: str,
        keywords: list[str],
        match_type: MatchType = "Broad",
        default_bid: float = 1.0,
    ) -> MutationResult:
        """Add keywords (Active) to an ad group.

        Args:
            ad_group_id: The ad group id.
            keywords: Keyword texts to add.
            match_type: "Broad", "Phrase", or "Exact" (default "Broad").
            default_bid: Default CPC bid in account currency (default 1.0).
        """
        return guarded(
            lambda: mutations.add_keywords(
                get_client(),
                ad_group_id=ad_group_id,
                keywords=keywords,
                match_type=match_type,
                default_bid=default_bid,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def create_responsive_search_ad(
        ad_group_id: str,
        final_url: str,
        headlines: list[str],
        descriptions: list[str],
        path1: str = "",
        path2: str = "",
    ) -> MutationResult:
        """Create a Responsive Search Ad (PAUSED).

        Args:
            ad_group_id: The ad group id.
            final_url: Landing page URL.
            headlines: 3-15 headlines (truncated to 30 chars each).
            descriptions: 2-4 descriptions (truncated to 90 chars each).
            path1: Optional display URL path 1 (max 15 chars).
            path2: Optional display URL path 2 (max 15 chars).
        """
        return guarded(
            lambda: mutations.create_responsive_search_ad(
                get_client(),
                ad_group_id=ad_group_id,
                final_url=final_url,
                headlines=headlines,
                descriptions=descriptions,
                path1=path1,
                path2=path2,
            )
        )
