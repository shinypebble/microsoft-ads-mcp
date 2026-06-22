"""Write tools — registered only when READ_ONLY is false. New entities are created paused."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..domain.entities import (
    AdScheduleInput,
    BidStrategyTypeInput,
    CampaignStatus,
    ConversionCountType,
    ConversionRevenueType,
    IntentOption,
    MatchType,
    MutationResult,
    NegativeEntityType,
    Network,
)
from ..services import (
    account_properties,
    bulk,
    conversions,
    criteria,
    extensions,
    mutations,
    negatives,
)
from ._common import guarded

_WRITE = ToolAnnotations(readOnlyHint=False)


def register(mcp: FastMCP) -> None:
    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def create_campaign(
        name: str,
        daily_budget: float,
        description: str = "",
        bid_strategy_type: BidStrategyTypeInput | None = None,
        max_cpc: float | None = None,
        target_cpa: float | None = None,
        target_roas: float | None = None,
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
        url_custom_parameters: dict[str, str] | None = None,
    ) -> MutationResult:
        """Create a Search campaign (PAUSED by default for safety).

        Args:
            name: Campaign name.
            daily_budget: Daily budget in account currency.
            description: Optional description.
            bid_strategy_type: The campaign's inline bid strategy. Omit to inherit Microsoft's
                default (EnhancedCpc). One of "EnhancedCpc", "ManualCpc", "MaxClicks",
                "MaxConversions", "TargetCpa", "MaxConversionValue", "TargetRoas".
            max_cpc: Optional Maximum CPC limit (account currency) for MaxClicks / MaxConversions /
                TargetCpa / MaxConversionValue / TargetRoas. Not valid for EnhancedCpc / ManualCpc.
            target_cpa: Target CPA (account currency) for TargetCpa / MaxConversions.
            target_roas: Target ROAS for TargetRoas / MaxConversionValue.
            tracking_url_template: Optional tracking template applied to all URLs in the
                campaign (e.g. "{lpurl}?utm_source=bing").
            final_url_suffix: Optional Final URL suffix appended to landing-page URLs.
            url_custom_parameters: Optional {key: value} URL custom parameters, referenced in
                templates/suffixes as {_key} (e.g. {"src": "bing"}).
        """
        return guarded(
            lambda: mutations.create_campaign(
                get_client(),
                name=name,
                daily_budget=daily_budget,
                description=description,
                bid_strategy_type=bid_strategy_type,
                max_cpc=max_cpc,
                target_cpa=target_cpa,
                target_roas=target_roas,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
                url_custom_parameters=url_custom_parameters,
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
        bid_strategy_type: BidStrategyTypeInput | None = None,
        max_cpc: float | None = None,
        target_cpa: float | None = None,
        target_roas: float | None = None,
        time_zone: str | None = None,
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
        url_custom_parameters: dict[str, str] | None = None,
    ) -> MutationResult:
        """Update an existing campaign in place. Only the fields you pass change.

        Args:
            campaign_id: The campaign id.
            name: New campaign name (rename).
            daily_budget: New daily budget in account currency.
            status: "Active" or "Paused".
            bid_strategy_id: Id of a portfolio (shared) bid strategy to apply. Mutually exclusive
                with bid_strategy_type.
            bid_strategy_type: Set the campaign's own inline bid strategy (BiddingScheme): one of
                "EnhancedCpc", "ManualCpc", "MaxClicks", "MaxConversions", "TargetCpa",
                "MaxConversionValue", "TargetRoas". e.g. "MaxClicks" (+ optional max_cpc) is
                Maximize Clicks with a Maximum CPC limit. The long-form value get_campaigns returns
                for TargetRoas / MaxConversionValue ("TargetRoasBiddingScheme" /
                "MaxConversionValueBiddingScheme") is also accepted, so a read value round-trips.
                Mutually exclusive with bid_strategy_id.
            max_cpc: Optional Maximum CPC limit (account currency) for MaxClicks / MaxConversions /
                TargetCpa / MaxConversionValue / TargetRoas. Not valid for EnhancedCpc / ManualCpc.
                get_campaigns reports the current value; re-pass it when changing bid_strategy_type
                or the existing cap may be cleared (the scheme is rewritten as a whole).
            target_cpa: Target CPA (account currency) for TargetCpa / MaxConversions. get_campaigns
                reports the current value; re-pass it to preserve it (see max_cpc).
            target_roas: Target ROAS for TargetRoas / MaxConversionValue. get_campaigns reports the
                current value; re-pass it to preserve it (see max_cpc).
            time_zone: Campaign time zone (Microsoft code, e.g. "CentralTimeUSCanada"); ad
                schedules run in this zone. Read the current value from get_campaigns.
            tracking_url_template: Tracking template for all URLs in the campaign.
            final_url_suffix: Final URL suffix appended to landing-page URLs.
            url_custom_parameters: {key: value} URL custom parameters, referenced in
                templates/suffixes as {_key}.
        """
        return guarded(
            lambda: mutations.update_campaign(
                get_client(),
                campaign_id=campaign_id,
                name=name,
                daily_budget=daily_budget,
                status=status,
                bid_strategy_id=bid_strategy_id,
                bid_strategy_type=bid_strategy_type,
                max_cpc=max_cpc,
                target_cpa=target_cpa,
                target_roas=target_roas,
                time_zone=time_zone,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
                url_custom_parameters=url_custom_parameters,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def create_ad_group(
        campaign_id: str,
        name: str,
        cpc_bid: float = 1.0,
        language: str = "English",
        network: Network | None = None,
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
        url_custom_parameters: dict[str, str] | None = None,
    ) -> MutationResult:
        """Create an ad group (PAUSED) in a campaign.

        Args:
            campaign_id: The parent campaign id.
            name: Ad group name.
            cpc_bid: Default CPC bid in account currency (default 1.0).
            language: Ad group language (required by Microsoft; default "English").
            network: Ad distribution (where the ad group serves). Omit to inherit Microsoft's
                default. "OwnedAndOperatedAndSyndicatedSearch" = the entire Microsoft Advertising
                Network (Microsoft sites + all syndicated partners); "OwnedAndOperatedOnly" =
                Microsoft sites and select traffic (a quality-screened partner subset).
            tracking_url_template: Optional tracking template for URLs in the ad group.
            final_url_suffix: Optional Final URL suffix appended to landing-page URLs.
            url_custom_parameters: Optional {key: value} URL custom parameters, referenced in
                templates/suffixes as {_key}.
        """
        return guarded(
            lambda: mutations.create_ad_group(
                get_client(),
                campaign_id=campaign_id,
                name=name,
                cpc_bid=cpc_bid,
                language=language,
                network=network,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
                url_custom_parameters=url_custom_parameters,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def update_ad_group(
        campaign_id: str,
        ad_group_id: str,
        name: str | None = None,
        status: CampaignStatus | None = None,
        cpc_bid: float | None = None,
        network: Network | None = None,
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
        url_custom_parameters: dict[str, str] | None = None,
    ) -> MutationResult:
        """Update an existing ad group in place. Only the fields you pass change.

        Args:
            campaign_id: The parent campaign id (required by Microsoft to update an ad group).
            ad_group_id: The ad group id.
            name: New ad group name (rename).
            status: "Active" or "Paused".
            cpc_bid: New default CPC bid in account currency.
            network: Ad distribution (where the ad group serves).
                "OwnedAndOperatedAndSyndicatedSearch" = the entire Microsoft Advertising Network;
                "OwnedAndOperatedOnly" = Microsoft sites and select traffic (a quality-screened
                partner subset). Read the current value from get_ad_groups.
            tracking_url_template: Tracking template for URLs in the ad group.
            final_url_suffix: Final URL suffix appended to landing-page URLs.
            url_custom_parameters: {key: value} URL custom parameters, referenced in
                templates/suffixes as {_key}.
        """
        return guarded(
            lambda: mutations.update_ad_group(
                get_client(),
                campaign_id=campaign_id,
                ad_group_id=ad_group_id,
                name=name,
                status=status,
                cpc_bid=cpc_bid,
                network=network,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
                url_custom_parameters=url_custom_parameters,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def add_keywords(
        ad_group_id: str,
        keywords: list[str],
        match_type: MatchType = "Broad",
        default_bid: float = 1.0,
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
        url_custom_parameters: dict[str, str] | None = None,
    ) -> MutationResult:
        """Add keywords (Active) to an ad group.

        Args:
            ad_group_id: The ad group id.
            keywords: Keyword texts to add.
            match_type: "Broad", "Phrase", or "Exact" (default "Broad").
            default_bid: Default CPC bid in account currency (default 1.0).
            tracking_url_template: Optional keyword-level tracking template (applies to every
                keyword in this batch; overrides ad-group/campaign templates).
            final_url_suffix: Optional Final URL suffix (applies to every keyword in this batch).
            url_custom_parameters: Optional {key: value} URL custom parameters, referenced in
                templates/suffixes as {_key} (applies to every keyword in this batch).
        """
        return guarded(
            lambda: mutations.add_keywords(
                get_client(),
                ad_group_id=ad_group_id,
                keywords=keywords,
                match_type=match_type,
                default_bid=default_bid,
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
                url_custom_parameters=url_custom_parameters,
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
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
        url_custom_parameters: dict[str, str] | None = None,
    ) -> MutationResult:
        """Update an existing keyword in place. Only the fields you pass change.

        Args:
            ad_group_id: The parent ad group id.
            keyword_id: The keyword id.
            bid: New CPC bid in account currency.
            match_type: "Broad", "Phrase", or "Exact".
            status: "Active" or "Paused".
            final_url: New keyword-level Final URL.
            tracking_url_template: Keyword-level tracking template (overrides ad-group/campaign).
            final_url_suffix: Keyword-level Final URL suffix.
            url_custom_parameters: {key: value} URL custom parameters, referenced in
                templates/suffixes as {_key}.
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
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
                url_custom_parameters=url_custom_parameters,
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
        url_custom_parameters: dict[str, str] | None = None,
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
            url_custom_parameters: Optional {key: value} URL custom parameters, referenced in
                templates/suffixes as {_key}.
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
                url_custom_parameters=url_custom_parameters,
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
        url_custom_parameters: dict[str, str] | None = None,
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
            url_custom_parameters: {key: value} URL custom parameters, referenced in
                templates/suffixes as {_key}.
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
                url_custom_parameters=url_custom_parameters,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def set_account_url_options(
        tracking_url_template: str | None = None,
        final_url_suffix: str | None = None,
        msclkid_auto_tagging_enabled: bool | None = None,
        ad_click_parallel_tracking: bool | None = None,
    ) -> MutationResult:
        """Set account-level URL options / tracking template (applies account-wide; every campaign
        inherits them).

        The cleanest way to apply a tracking template (tracking URL template), Final URL suffix,
        msclkid auto-tagging, or parallel tracking across the whole account at once -- the inherited
        URL settings -- instead of editing each campaign/ad/keyword. Only the fields you pass
        change. Read the current values first with get_account_url_options, and use
        get_effective_url_settings to confirm what a given campaign/ad group resolves to afterward.

        Args:
            tracking_url_template: Account tracking template, e.g.
                "{lpurl}?utm_source=bing&utm_medium=cpc&utm_campaign={campaign}". Pass "" to clear.
            final_url_suffix: Account Final URL suffix appended to landing-page URLs ("" clears).
            msclkid_auto_tagging_enabled: Whether to auto-append the Microsoft Click ID (msclkid)
                used for conversion attribution.
            ad_click_parallel_tracking: Whether to enable parallel tracking.
        """
        return guarded(
            lambda: account_properties.set_account_url_options(
                get_client(),
                tracking_url_template=tracking_url_template,
                final_url_suffix=final_url_suffix,
                msclkid_auto_tagging_enabled=msclkid_auto_tagging_enabled,
                ad_click_parallel_tracking=ad_click_parallel_tracking,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def delete_campaign(campaign_ids: list[str]) -> MutationResult:
        """Delete one or more campaigns by id.

        Args:
            campaign_ids: The campaign ids to delete.
        """
        return guarded(lambda: mutations.delete_campaigns(get_client(), campaign_ids=campaign_ids))

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
        is_call_tracking_enabled: bool | None = None,
    ) -> MutationResult:
        """Update an existing call extension in place (e.g. the brand's phone number or tracking).

        Microsoft replaces the whole call extension on update, so phone number and country code
        are always required; when you omit them (e.g. to flip only is_call_tracking_enabled) this
        tool fetches the current extension and re-sends them, so a single-field toggle is safe.

        Args:
            ad_extension_id: The call extension id (from get_ad_extensions).
            phone_number: New phone number (omit to keep the current one).
            country_code: Two-letter country code for the number, e.g. "US" (omit to keep current).
            is_call_only: Whether the extension shows only the phone number (no website click).
            is_call_tracking_enabled: Turn Microsoft call tracking on/off (US/UK only). When on,
                Microsoft displays a forwarding number so call conversions are measured (new
                forwarding numbers are local, not toll-free). Pass true to enable tracking on an
                existing plain call asset.
        """
        return guarded(
            lambda: extensions.update_call_extension(
                get_client(),
                ad_extension_id=ad_extension_id,
                phone_number=phone_number,
                country_code=country_code,
                is_call_only=is_call_only,
                is_call_tracking_enabled=is_call_tracking_enabled,
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
    def add_call_extension(
        phone_number: str,
        country_code: str = "US",
        is_call_only: bool = False,
        is_call_tracking_enabled: bool = False,
        entity_id: str | None = None,
        association_type: str = "Campaign",
    ) -> MutationResult:
        """Create a call extension and optionally attach it to a campaign or ad group.

        Args:
            phone_number: The phone number to show (e.g. "2065550100").
            country_code: Two-letter country code for the number (default "US").
            is_call_only: Whether the extension shows only the phone number (no website click).
            is_call_tracking_enabled: Turn on Microsoft call tracking (US/UK only) so call-from-ad
                conversions are measured. Microsoft displays a forwarding number instead of the
                raw number; new forwarding numbers are local (toll-free is no longer provisioned).
            entity_id: Campaign or ad group id to associate it with (omit to create unattached).
            association_type: "Campaign" or "AdGroup" (default "Campaign").
        """
        return guarded(
            lambda: extensions.add_call_extension(
                get_client(),
                phone_number=phone_number,
                country_code=country_code,
                is_call_only=is_call_only,
                is_call_tracking_enabled=is_call_tracking_enabled,
                entity_id=entity_id,
                association_type=association_type,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def delete_ad_extension(ad_extension_ids: list[str]) -> MutationResult:
        """Delete account-level ad extensions by id.

        Removes the extension objects entirely (not just their campaign/ad-group associations).

        Args:
            ad_extension_ids: The ad extension ids to delete (from get_ad_extensions).
        """
        return guarded(
            lambda: extensions.delete_ad_extensions(get_client(), ad_extension_ids=ad_extension_ids)
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def update_conversion_goal(
        goal_id: str,
        name: str | None = None,
        status: CampaignStatus | None = None,
        exclude_from_bidding: bool | None = None,
        count_type: ConversionCountType | None = None,
        conversion_window_in_minutes: int | None = None,
        revenue_type: ConversionRevenueType | None = None,
        revenue_value: float | None = None,
        revenue_currency_code: str | None = None,
    ) -> MutationResult:
        """Update a conversion goal in place. Only the fields you pass change.

        The key bidding lever is `exclude_from_bidding` — the inverse of the web UI's "Include in
        conversions" checkbox. `exclude_from_bidding=false` keeps the goal in the Conversions
        column and in automated-bidding math (ECPC / tCPA); `true` drops it from both (it still
        reports under All conversions). Confirm this is false before relying on a goal to steer
        spend. Read the current values first with get_conversion_goals.

        Args:
            goal_id: The conversion goal id (from get_conversion_goals).
            name: New goal name (rename).
            status: "Active" or "Paused" (a paused goal stops recording conversions).
            exclude_from_bidding: false = include the goal in the Conversions column and automated
                bidding; true = exclude it from both (still tracked under All conversions).
            count_type: How conversions are counted per click — "All" (every conversion) or
                "Unique" (one per click).
            conversion_window_in_minutes: Click-to-conversion lookback window in minutes (e.g.
                43200 = 30 days).
            revenue_type: Conversion value model — "FixedValue" (same value each time, requires
                revenue_value), "VariableValue" (value sent with the event), or "NoValue". Revenue
                fields are merged onto the goal's current revenue, so you can change one without
                re-stating the others.
            revenue_value: Revenue amount (required for "FixedValue"; the default for
                "VariableValue").
            revenue_currency_code: ISO currency code for the revenue value, e.g. "USD".
        """
        return guarded(
            lambda: conversions.update_conversion_goal(
                get_client(),
                goal_id=goal_id,
                name=name,
                status=status,
                exclude_from_bidding=exclude_from_bidding,
                count_type=count_type,
                conversion_window_in_minutes=conversion_window_in_minutes,
                revenue_type=revenue_type,
                revenue_value=revenue_value,
                revenue_currency_code=revenue_currency_code,
            )
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
    def set_location_intent(campaign_id: str, intent_option: IntentOption) -> MutationResult:
        """Set who sees a campaign's ads relative to its targeted locations (location intent).

        Updates the campaign's single LocationIntent criterion in place (created by Microsoft
        with a default of "PeopleInOrSearchingForOrViewingPages"). Read the current value first
        with get_location_intent.

        Args:
            campaign_id: The campaign id.
            intent_option: "PeopleIn" (presence — only people physically in/regularly in the
                targeted locations) or "PeopleInOrSearchingForOrViewingPages" (people in,
                searching for, or viewing pages about them; Microsoft's default). The legacy
                "search-interest-only" option was deprecated by Microsoft in April 2024.
        """
        return guarded(
            lambda: criteria.set_location_intent(
                get_client(), campaign_id=campaign_id, intent_option=intent_option
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def set_device_bid_adjustment(
        campaign_id: str, device: str, bid_adjustment: float
    ) -> MutationResult:
        """Set a campaign's bid adjustment for one device (e.g. a mobile modifier).

        Microsoft calls mobile "Smartphones" (there is no "Mobile"); "Computers" is desktop/laptop.
        Device criterions are created as a set, so the first time you set any device this also
        creates the other two at a neutral 0. Read the current values first with
        get_device_bid_adjustments.

        Args:
            campaign_id: The campaign id.
            device: The device to adjust. Canonical values are "Computers", "Smartphones", and
                "Tablets"; the friendly aliases "mobile" (-> Smartphones), "desktop"/"pc" (->
                Computers), and "tablet" are also accepted (case-insensitive).
            bid_adjustment: Percent modifier from -100 to 900 (e.g. 40 = +40%); -100 excludes the
                device from serving entirely.
        """
        return guarded(
            lambda: criteria.set_device_bid_adjustment(
                get_client(),
                campaign_id=campaign_id,
                device=device,
                bid_adjustment=bid_adjustment,
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
    def add_ad_schedules(
        campaign_id: str,
        schedules: list[AdScheduleInput],
        use_searcher_time_zone: bool | None = None,
    ) -> MutationResult:
        """Add ad-schedule (dayparting) windows to a campaign.

        Each window restricts serving to one day and time range and is additive (a campaign with
        no schedule serves all hours). Hours are 0-24; minutes are 15-minute granularity, so only
        0/15/30/45 are valid (e.g. 09:15-16:45 -> from_hour 9, from_minute 15, to_hour 16,
        to_minute 45). Times run in the campaign time zone (see get_campaigns / get_ad_schedules)
        unless you pass use_searcher_time_zone=true. Read existing windows with get_ad_schedules
        first to avoid duplicates.

        Args:
            campaign_id: The campaign id.
            schedules: Windows to add, each {day, from_hour, from_minute, to_hour, to_minute,
                bid_adjustment}. day is "Monday".."Sunday"; bid_adjustment is a percent modifier
                (0 = no change).
            use_searcher_time_zone: If set, also updates the campaign flag controlling whether the
                hours are interpreted in each searcher's time zone (true) or the campaign's (false).
        """
        return guarded(
            lambda: criteria.add_ad_schedules(
                get_client(),
                campaign_id=campaign_id,
                schedules=schedules,
                use_searcher_time_zone=use_searcher_time_zone,
            )
        )

    @mcp.tool(tags={"write"}, annotations=_WRITE)
    def remove_ad_schedules(campaign_id: str, criterion_ids: list[str]) -> MutationResult:
        """Remove ad-schedule (dayparting) windows from a campaign by criterion id.

        Args:
            campaign_id: The campaign id.
            criterion_ids: Campaign criterion ids (from get_ad_schedules).
        """
        return guarded(
            lambda: criteria.remove_ad_schedules(
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
