"""Write tools — registered only when READ_ONLY is false. New entities are created paused."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..domain.entities import CampaignStatus, MatchType, MutationResult, NegativeEntityType
from ..services import bulk, conversions, criteria, extensions, mutations, negatives
from ._common import guarded

_WRITE = ToolAnnotations(readOnlyHint=False)


def register(mcp: FastMCP) -> None:
    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def create_campaign(
        name: str,
        daily_budget: float,
        description: str = "",
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
    ) -> MutationResult:
        """Create a Search campaign (PAUSED by default for safety).

        Args:
            name: Campaign name.
            daily_budget: Daily budget in account currency.
            description: Optional description.
            tracking_url_template: Optional tracking template applied to all URLs in the
                campaign (e.g. "{lpurl}?utm_source=bing").
            final_url_suffix: Optional Final URL suffix appended to landing-page URLs.
        """
        return guarded(
            lambda: mutations.create_campaign(
                get_client(),
                name=name,
                daily_budget=daily_budget,
                description=description,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
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
    def update_campaign(
        campaign_id: str,
        name: str | None = None,
        daily_budget: float | None = None,
        status: CampaignStatus | None = None,
        bid_strategy_id: str | None = None,
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
    ) -> MutationResult:
        """Update an existing campaign in place. Only the fields you pass change.

        Args:
            campaign_id: The campaign id.
            name: New campaign name (rename).
            daily_budget: New daily budget in account currency.
            status: "Active" or "Paused".
            bid_strategy_id: Id of a portfolio bid strategy to apply.
            tracking_url_template: Tracking template for all URLs in the campaign.
            final_url_suffix: Final URL suffix appended to landing-page URLs.
        """
        return guarded(
            lambda: mutations.update_campaign(
                get_client(),
                campaign_id=campaign_id,
                name=name,
                daily_budget=daily_budget,
                status=status,
                bid_strategy_id=bid_strategy_id,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def create_ad_group(
        campaign_id: str,
        name: str,
        cpc_bid: float = 1.0,
        language: str = "English",
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
    ) -> MutationResult:
        """Create an ad group (PAUSED) in a campaign.

        Args:
            campaign_id: The parent campaign id.
            name: Ad group name.
            cpc_bid: Default CPC bid in account currency (default 1.0).
            language: Ad group language (required by Microsoft; default "English").
            tracking_url_template: Optional tracking template for URLs in the ad group.
            final_url_suffix: Optional Final URL suffix appended to landing-page URLs.
        """
        return guarded(
            lambda: mutations.create_ad_group(
                get_client(),
                campaign_id=campaign_id,
                name=name,
                cpc_bid=cpc_bid,
                language=language,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def update_ad_group(
        campaign_id: str,
        ad_group_id: str,
        name: str | None = None,
        status: CampaignStatus | None = None,
        cpc_bid: float | None = None,
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
    ) -> MutationResult:
        """Update an existing ad group in place. Only the fields you pass change.

        Args:
            campaign_id: The parent campaign id (required by Microsoft to update an ad group).
            ad_group_id: The ad group id.
            name: New ad group name (rename).
            status: "Active" or "Paused".
            cpc_bid: New default CPC bid in account currency.
            tracking_url_template: Tracking template for URLs in the ad group.
            final_url_suffix: Final URL suffix appended to landing-page URLs.
        """
        return guarded(
            lambda: mutations.update_ad_group(
                get_client(),
                campaign_id=campaign_id,
                ad_group_id=ad_group_id,
                name=name,
                status=status,
                cpc_bid=cpc_bid,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
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
    def update_keyword(
        ad_group_id: str,
        keyword_id: str,
        bid: float | None = None,
        match_type: MatchType | None = None,
        status: CampaignStatus | None = None,
        final_url: str | None = None,
    ) -> MutationResult:
        """Update an existing keyword in place. Only the fields you pass change.

        Args:
            ad_group_id: The parent ad group id.
            keyword_id: The keyword id.
            bid: New CPC bid in account currency.
            match_type: "Broad", "Phrase", or "Exact".
            status: "Active" or "Paused".
            final_url: New keyword-level Final URL.
        """
        return guarded(
            lambda: mutations.update_keyword(
                get_client(),
                ad_group_id=ad_group_id,
                keyword_id=keyword_id,
                bid=bid,
                match_type=match_type,
                status=status,
                final_url=final_url,
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
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
    ) -> MutationResult:
        """Create a Responsive Search Ad (PAUSED).

        Args:
            ad_group_id: The ad group id.
            final_url: Landing page URL.
            headlines: 3-15 headlines (truncated to 30 chars each).
            descriptions: 2-4 descriptions (truncated to 90 chars each).
            path1: Optional display URL path 1 (max 15 chars).
            path2: Optional display URL path 2 (max 15 chars).
            tracking_url_template: Optional tracking template for this ad's URLs.
            final_url_suffix: Optional Final URL suffix appended to landing-page URLs.
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
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def update_responsive_search_ad(
        ad_group_id: str,
        ad_id: str,
        final_url: str | None = None,
        headlines: list[str] | None = None,
        descriptions: list[str] | None = None,
        path1: str | None = None,
        path2: str | None = None,
        status: CampaignStatus | None = None,
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
    ) -> MutationResult:
        """Update an existing Responsive Search Ad in place. Only the fields you pass change.

        Use this to repoint a Final URL or refresh copy without recreating the ad.

        Args:
            ad_group_id: The parent ad group id.
            ad_id: The ad id (from get_ads).
            final_url: New landing page URL.
            headlines: Replacement headlines (3-15; truncated to 30 chars each).
            descriptions: Replacement descriptions (2-4; truncated to 90 chars each).
            path1: New display URL path 1 (max 15 chars).
            path2: New display URL path 2 (max 15 chars).
            status: "Active" or "Paused".
            tracking_url_template: Tracking template for this ad's URLs.
            final_url_suffix: Final URL suffix appended to landing-page URLs.
        """
        return guarded(
            lambda: mutations.update_responsive_search_ad(
                get_client(),
                ad_group_id=ad_group_id,
                ad_id=ad_id,
                final_url=final_url,
                headlines=headlines,
                descriptions=descriptions,
                path1=path1,
                path2=path2,
                status=status,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def delete_campaign(campaign_ids: list[str]) -> MutationResult:
        """Delete one or more campaigns by id.

        Args:
            campaign_ids: The campaign ids to delete.
        """
        return guarded(
            lambda: mutations.delete_campaigns(get_client(), campaign_ids=campaign_ids)
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def delete_ad_group(campaign_id: str, ad_group_ids: list[str]) -> MutationResult:
        """Delete one or more ad groups by id.

        Args:
            campaign_id: The parent campaign id.
            ad_group_ids: The ad group ids to delete.
        """
        return guarded(
            lambda: mutations.delete_ad_groups(
                get_client(), campaign_id=campaign_id, ad_group_ids=ad_group_ids
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def delete_ad(ad_group_id: str, ad_ids: list[str]) -> MutationResult:
        """Delete one or more ads by id.

        Args:
            ad_group_id: The parent ad group id.
            ad_ids: The ad ids to delete.
        """
        return guarded(
            lambda: mutations.delete_ads(get_client(), ad_group_id=ad_group_id, ad_ids=ad_ids)
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def delete_keyword(ad_group_id: str, keyword_ids: list[str]) -> MutationResult:
        """Delete one or more keywords by id.

        Args:
            ad_group_id: The parent ad group id.
            keyword_ids: The keyword ids to delete.
        """
        return guarded(
            lambda: mutations.delete_keywords(
                get_client(), ad_group_id=ad_group_id, keyword_ids=keyword_ids
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def add_negative_keywords(
        entity_id: str,
        keywords: list[str],
        entity_type: NegativeEntityType = "Campaign",
        match_type: MatchType = "Exact",
    ) -> MutationResult:
        """Attach negative keywords to a campaign or ad group.

        Args:
            entity_id: The campaign id (or ad group id) to attach negatives to.
            keywords: Negative keyword texts to add.
            entity_type: "Campaign" or "AdGroup" (default "Campaign").
            match_type: "Broad", "Phrase", or "Exact" (default "Exact").
        """
        return guarded(
            lambda: negatives.add_negative_keywords(
                get_client(),
                entity_id=entity_id,
                entity_type=entity_type,
                keywords=keywords,
                match_type=match_type,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def remove_negative_keywords(
        entity_id: str,
        keyword_ids: list[str],
        entity_type: NegativeEntityType = "Campaign",
    ) -> MutationResult:
        """Remove negative keywords from a campaign or ad group, identified by id.

        Resolve ids first with get_negative_keywords (deletion is by id, not text).

        Args:
            entity_id: The campaign id (or ad group id) the negatives are attached to.
            keyword_ids: The negative keyword ids to remove.
            entity_type: "Campaign" or "AdGroup" (default "Campaign").
        """
        return guarded(
            lambda: negatives.remove_negative_keywords(
                get_client(),
                entity_id=entity_id,
                entity_type=entity_type,
                keyword_ids=keyword_ids,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def update_call_extension(
        ad_extension_id: str,
        phone_number: str | None = None,
        country_code: str | None = None,
        is_call_only: bool | None = None,
    ) -> MutationResult:
        """Update an existing call extension in place (e.g. the brand's phone number).

        Args:
            ad_extension_id: The call extension id (from get_ad_extensions).
            phone_number: New phone number.
            country_code: Two-letter country code for the number (e.g. "US").
            is_call_only: Whether the extension shows only the phone number (no website click).
        """
        return guarded(
            lambda: extensions.update_call_extension(
                get_client(),
                ad_extension_id=ad_extension_id,
                phone_number=phone_number,
                country_code=country_code,
                is_call_only=is_call_only,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def add_callout_extension(
        text: str,
        entity_id: str | None = None,
        association_type: str = "Campaign",
    ) -> MutationResult:
        """Create a callout extension and optionally attach it to a campaign or ad group.

        Args:
            text: Callout text (max 25 chars).
            entity_id: Campaign or ad group id to associate it with (omit to create unattached).
            association_type: "Campaign" or "AdGroup" (default "Campaign").
        """
        return guarded(
            lambda: extensions.add_callout_extension(
                get_client(),
                text=text,
                entity_id=entity_id,
                association_type=association_type,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def add_sitelink_extension(
        display_text: str,
        final_url: str,
        entity_id: str | None = None,
        association_type: str = "Campaign",
    ) -> MutationResult:
        """Create a sitelink extension and optionally attach it to a campaign or ad group.

        Args:
            display_text: Sitelink link text (max 25 chars).
            final_url: Landing page URL for the sitelink.
            entity_id: Campaign or ad group id to associate it with (omit to create unattached).
            association_type: "Campaign" or "AdGroup" (default "Campaign").
        """
        return guarded(
            lambda: extensions.add_sitelink_extension(
                get_client(),
                display_text=display_text,
                final_url=final_url,
                entity_id=entity_id,
                association_type=association_type,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def update_conversion_goal(goal_id: str, name: str) -> MutationResult:
        """Rename a conversion goal in place.

        Args:
            goal_id: The conversion goal id (from get_conversion_goals).
            name: The new goal name.
        """
        return guarded(
            lambda: conversions.update_conversion_goal(get_client(), goal_id=goal_id, name=name)
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def update_uet_tag(
        tag_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> MutationResult:
        """Update a UET tag's name and/or description in place.

        Args:
            tag_id: The UET tag id (from get_uet_tags).
            name: New tag name.
            description: New tag description.
        """
        return guarded(
            lambda: conversions.update_uet_tag(
                get_client(), tag_id=tag_id, name=name, description=description
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def add_location_targets(
        campaign_id: str,
        location_ids: list[str],
        bid_adjustment: float = 0.0,
        exclude: bool = False,
    ) -> MutationResult:
        """Target (or exclude) Microsoft LocationIds on a campaign.

        Resolve ZIPs to LocationIds first with resolve_postal_codes.

        Args:
            campaign_id: The campaign id.
            location_ids: Microsoft LocationIds to target/exclude.
            bid_adjustment: Percent bid modifier for targeted locations (ignored when exclude).
            exclude: When true, exclude these locations instead of targeting them.
        """
        return guarded(
            lambda: criteria.add_location_targets(
                get_client(),
                campaign_id=campaign_id,
                location_ids=location_ids,
                bid_adjustment=bid_adjustment,
                exclude=exclude,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def remove_location_targets(campaign_id: str, criterion_ids: list[str]) -> MutationResult:
        """Remove location targets/exclusions from a campaign by criterion id.

        Args:
            campaign_id: The campaign id.
            criterion_ids: Campaign criterion ids (from get_location_targets).
        """
        return guarded(
            lambda: criteria.remove_location_targets(
                get_client(), campaign_id=campaign_id, criterion_ids=criterion_ids
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def bulk_upload(entity_records: list[str]) -> dict[str, Any]:
        """Apply ready-made Bulk CSV rows to the account; polls to completion.

        Args:
            entity_records: Bulk-file CSV rows (including the Format Version / Type header rows
                Microsoft expects). Returns the request status and result file URL.
        """
        return guarded(lambda: bulk.bulk_upload(get_client(), entity_records=entity_records))
