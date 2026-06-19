"""Ad Insight tools: keyword research -- bid estimates, keyword ideas, traffic estimates.

These are read-only "planner" tools (Microsoft's Ad Insight service). They return modeled
estimates, not live account data, so they are always registered regardless of the READ_ONLY gate.
"""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..domain.entities import (
    FirstPageBidReport,
    KeywordBidEstimate,
    KeywordIdeaSummary,
    KeywordTrafficEstimate,
)
from ..services import insights
from ._common import guarded

_READ = ToolAnnotations(readOnlyHint=True)


def register(mcp: FastMCP) -> None:
    @mcp.tool(tags={"read"}, annotations=_READ)
    def estimate_keyword_bids(
        keywords: list[str],
        target_position: str = "FirstPage",
        match_types: list[str] | None = None,
        currency_code: str | None = None,
        language: str | None = None,
        location_ids: list[str] | None = None,
    ) -> list[KeywordBidEstimate]:
        """Estimate the bid to reach the first page (or mainline) for keywords -- the "estimated
        first page bid" from Keyword Planner.

        For each keyword, returns one estimate per match type: `estimated_min_bid` (the headline
        first-page/mainline bid) plus modeled average CPC, CTR, and weekly clicks/impressions/cost
        ranges. Estimates are account-scoped and may be null where Microsoft has no data.

        Args:
            keywords: Keyword texts to price, e.g. ["running shoes", "trail running shoes"].
            target_position: "FirstPage" (default), "MainLine", or "MainLine1" (top ad slot).
            match_types: Subset of ["Broad", "Phrase", "Exact"]; defaults to ["Exact"].
            currency_code: ISO currency for the bids (e.g. "USD"); defaults to the account currency.
            language: Language name for the estimate, e.g. "English" (optional).
            location_ids: Microsoft location ids to scope demand to (optional).
        """
        return guarded(
            lambda: insights.estimate_keyword_bids(
                get_client(),
                keywords=keywords,
                target_position=target_position,
                match_types=match_types,
                currency_code=currency_code,
                language=language,
                location_ids=location_ids,
            )
        )

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_keyword_ideas(
        keywords: list[str] | None = None,
        url: str | None = None,
        language: str = "English",
        location_ids: list[str] | None = None,
        network: str = "OwnedAndOperatedAndSyndicatedSearch",
        expand_ideas: bool = True,
        max_results: int = 100,
    ) -> list[KeywordIdeaSummary]:
        """Discover keyword ideas from seed phrases and/or a landing-page URL (Keyword Planner).

        Each idea reports `avg_monthly_searches` (+ the monthly history), a rough `suggested_bid`,
        and a `competition` bucket (Low/Medium/High). Provide at least one of `keywords` or `url`.

        Args:
            keywords: Seed phrases to expand, e.g. ["running shoes"].
            url: A landing page to mine for related keywords, e.g. "contoso.com/shoes".
            language: Exactly one language name (default "English").
            location_ids: Microsoft location ids; defaults to the United States ("190").
            network: "OwnedAndOperatedAndSyndicatedSearch" (default), "OwnedAndOperatedOnly",
                or "SyndicatedSearchOnly".
            expand_ideas: Expand beyond the seeds to related keywords (default True). When False,
                `keywords` is required and only those seeds are scored.
            max_results: Cap on returned ideas (default 100).
        """
        return guarded(
            lambda: insights.get_keyword_ideas(
                get_client(),
                keywords=keywords,
                url=url,
                language=language,
                location_ids=location_ids,
                network=network,
                expand_ideas=expand_ideas,
                max_results=max_results,
            )
        )

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_keyword_traffic_estimates(
        keywords: list[str],
        max_cpc: float,
        match_type: str = "Exact",
        language: str = "English",
        location_ids: list[str] | None = None,
        network: str = "OwnedAndOperatedAndSyndicatedSearch",
    ) -> list[KeywordTrafficEstimate]:
        """Estimate weekly traffic (clicks/impressions/cost/position) for keywords at a given bid.

        Each keyword's estimate is a min..max bracket at the supplied `max_cpc` and match type --
        useful to gauge search volume and likely spend before launching. (`estimate_keyword_bids`
        also returns weekly clicks/impressions/cost, so reach for this when you specifically want
        the traffic at a bid you choose rather than at the first-page suggested bid.)

        Args:
            keywords: Keyword texts to estimate, e.g. ["running shoes", "trail running shoes"].
            max_cpc: The max CPC bid to model, in account currency (e.g. 2.50).
            match_type: "Exact" (default), "Phrase", or "Broad".
            language: Exactly one language name (default "English").
            location_ids: Microsoft location ids; defaults to the United States ("190").
            network: "OwnedAndOperatedAndSyndicatedSearch" (default), "OwnedAndOperatedOnly",
                or "SyndicatedSearchOnly".
        """
        return guarded(
            lambda: insights.get_keyword_traffic_estimates(
                get_client(),
                keywords=keywords,
                max_cpc=max_cpc,
                match_type=match_type,
                language=language,
                location_ids=location_ids,
                network=network,
            )
        )

    @mcp.tool(tags={"read"}, annotations=_READ)
    def check_first_page_bids(
        ad_group_id: str,
        campaign_id: str,
        target_position: str = "FirstPage",
        language: str | None = None,
        location_ids: list[str] | None = None,
    ) -> FirstPageBidReport:
        """Flag keywords whose bid is below the estimated first-page bid ("Below first page bid").

        This is the API-driven version of the delivery state the UI shows as "Below first page
        bid". For each keyword in the ad group it looks up the Keyword Planner first-page bid
        estimate (at the keyword's own match type) and compares it against the keyword's effective
        bid -- the keyword's own bid, or the ad group's default bid when the keyword has none. The
        result lists the under-bid keywords first (largest `shortfall` first) with each one's
        `current_bid`, `estimated_first_page_bid`, and `bid_source`, plus counts. Use it when
        diagnosing low impressions, or before activating a campaign, to find keywords that won't
        reach the first page at their current bid.

        Args:
            ad_group_id: The ad group whose keywords to check.
            campaign_id: The parent campaign id -- required to read the ad group's default bid,
                which keywords without their own bid inherit.
            target_position: "FirstPage" (default), "MainLine", or "MainLine1" (top ad slot).
            language: Language name for the estimate, e.g. "English" (optional).
            location_ids: Microsoft location ids to scope demand to; the estimate defaults to the
                United States ("190") when omitted.
        """
        return guarded(
            lambda: insights.check_first_page_bids(
                get_client(),
                ad_group_id=ad_group_id,
                campaign_id=campaign_id,
                target_position=target_position,
                language=language,
                location_ids=location_ids,
            )
        )
