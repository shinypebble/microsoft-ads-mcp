"""Read tools: accounts, campaigns, ad groups, keywords, ads, budgets."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..domain.entities import (
    AccountSummary,
    AccountUrlOptions,
    AdExtensionSummary,
    AdGroupSummary,
    AdScheduleSettings,
    AdSummary,
    CampaignSummary,
    ConversionGoalSummary,
    DeviceBidAdjustmentSummary,
    KeywordSummary,
    LocationCriterionSummary,
    LocationIntentSummary,
    NegativeEntityType,
    NegativeKeywordSummary,
    PostalCodeLocation,
    UetTagSummary,
)
from ..services import (
    account_properties,
    accounts,
    bulk,
    campaigns,
    conversions,
    criteria,
    extensions,
    geo,
    negatives,
)
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

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_account_url_options() -> AccountUrlOptions:
        """Read the account-level URL tracking that every campaign inherits.

        This is where the tracking template / Final URL suffix usually live; per-campaign,
        ad-group, ad, and keyword values are typically blank and inherit from here, so check
        this (not just the hierarchy) to confirm how clicks are tracked.
        `msclkid_auto_tagging_enabled` is what appends the Microsoft Click ID (msclkid) for
        conversion attribution. Confirm these before activating paused campaigns.
        """
        return guarded(lambda: account_properties.get_account_url_options(get_client()))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_negative_keywords(
        entity_ids: list[str],
        entity_type: NegativeEntityType = "Campaign",
        parent_entity_id: str | None = None,
    ) -> list[NegativeKeywordSummary]:
        """List negative keywords attached to campaigns or ad groups.

        Args:
            entity_ids: Campaign ids (or ad group ids) to read negatives from.
            entity_type: "Campaign" or "AdGroup" (default "Campaign").
            parent_entity_id: For entity_type "AdGroup", the parent campaign id (required).
        """
        return guarded(
            lambda: negatives.get_negative_keywords(
                get_client(),
                entity_ids=entity_ids,
                entity_type=entity_type,
                parent_entity_id=parent_entity_id,
            )
        )

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_ad_extensions(
        extension_types: list[str] | None = None,
        association_type: str = "Account",
    ) -> list[AdExtensionSummary]:
        """List ad extensions in the account (call, callout, sitelink, etc.).

        Args:
            extension_types: Optional filter, e.g. ["Call", "Sitelink"]; defaults to all types.
            association_type: Scope to enumerate ids from: "Account", "Campaign", or "AdGroup"
                (default "Account").
        """
        return guarded(
            lambda: extensions.get_ad_extensions(
                get_client(),
                extension_types=extension_types,
                association_type=association_type,
            )
        )

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_conversion_goals(goal_ids: list[str] | None = None) -> list[ConversionGoalSummary]:
        """List conversion goals (all types). Pass goal_ids to fetch specific goals.

        Each goal reports `exclude_from_bidding` — the inverse of the UI's "Include in
        conversions" checkbox and the single switch for whether the goal steers automated
        bidding: false means it counts in the Conversions column and ECPC/tCPA bid math, true
        means it only shows under All conversions. Also surfaces `count_type` (All/Unique),
        `conversion_window_in_minutes`, `goal_category`, and the revenue model (`revenue_type` /
        `revenue_value` / `revenue_currency_code`). Confirm `exclude_from_bidding` is false before
        relying on a goal to drive spend; flip it with update_conversion_goal.

        Args:
            goal_ids: Optional conversion goal ids; omit to list all goals in the account.
        """
        return guarded(lambda: conversions.get_conversion_goals(get_client(), goal_ids=goal_ids))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_uet_tags(tag_ids: list[str] | None = None) -> list[UetTagSummary]:
        """List UET tags. Pass tag_ids to fetch specific tags.

        Args:
            tag_ids: Optional UET tag ids; omit to list all tags in the account.
        """
        return guarded(lambda: conversions.get_uet_tags(get_client(), tag_ids=tag_ids))

    @mcp.tool(tags={"read"}, annotations=ToolAnnotations(readOnlyHint=False))
    def set_active_account(account_id: str, customer_id: str | None = None) -> dict[str, str]:
        """Switch which account subsequent tool calls read from and write to (this session only).

        Use search_accounts to find ids. The OAuth credential is unchanged; this only rescopes
        calls. Confirm the target with account_health afterwards before any write.

        Args:
            account_id: The advertising account id to make active.
            customer_id: Optional manager (customer) id that owns the account.
        """

        def _switch() -> dict[str, str]:
            client = get_client()
            client.set_account(account_id, customer_id)
            return {
                "account_id": str(client.account_id),
                "customer_id": str(client.customer_id) if client.customer_id else "",
                "message": f"Active account set to {account_id}",
            }

        return guarded(_switch)

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_location_targets(campaign_id: str) -> list[LocationCriterionSummary]:
        """List the location targets/exclusions on a campaign.

        Args:
            campaign_id: The campaign id.
        """
        return guarded(lambda: criteria.get_location_targets(get_client(), campaign_id=campaign_id))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_location_intent(campaign_id: str) -> LocationIntentSummary | None:
        """Read a campaign's location-intent setting (presence vs. broader reach).

        Returns the single LocationIntent criterion's `intent_option`: `PeopleIn` (only people
        physically in the targeted locations) or `PeopleInOrSearchingForOrViewingPages` (people
        in, searching for, or viewing pages about them; Microsoft's default). Legacy campaigns
        may still report the deprecated `PeopleSearchingForOrViewingPages`.

        Args:
            campaign_id: The campaign id.
        """
        return guarded(lambda: criteria.get_location_intent(get_client(), campaign_id=campaign_id))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_ad_schedules(campaign_id: str) -> AdScheduleSettings:
        """Read a campaign's ad-schedule (dayparting) windows and their time-zone context.

        Returns each window (`day`, `from_hour`/`from_minute`, `to_hour`/`to_minute`,
        `bid_adjustment`) plus the campaign's `time_zone` and `use_searcher_time_zone` flag. When
        `use_searcher_time_zone` is false, the hours run in the campaign `time_zone`; remove a
        window with `remove_ad_schedules` using its `criterion_id`.

        Args:
            campaign_id: The campaign id.
        """
        return guarded(lambda: criteria.get_ad_schedules(get_client(), campaign_id=campaign_id))

    @mcp.tool(tags={"read"}, annotations=_READ)
    def get_device_bid_adjustments(campaign_id: str) -> list[DeviceBidAdjustmentSummary]:
        """Read a campaign's device bid adjustments (Computers / Smartphones / Tablets).

        Each row's `bid_adjustment` is a percent modifier (-100 to 900; -100 excludes the device).
        An empty list means no device modifier is set, so every device serves at the base bid.
        Note Microsoft calls mobile "Smartphones". Set one with `set_device_bid_adjustment`.

        Args:
            campaign_id: The campaign id.
        """
        return guarded(
            lambda: criteria.get_device_bid_adjustments(get_client(), campaign_id=campaign_id)
        )

    @mcp.tool(tags={"read"}, annotations=_READ)
    def resolve_postal_codes(
        postal_codes: list[str], language_locale: str = "en"
    ) -> list[PostalCodeLocation]:
        """Resolve ZIP / postal codes to Microsoft LocationIds (for location targeting).

        Downloads and caches Microsoft's geo-locations file on first use.

        Args:
            postal_codes: ZIP / postal codes to resolve, e.g. ["98101", "98052"].
            language_locale: Geo file locale (default "en").
        """
        return guarded(
            lambda: geo.resolve_postal_codes(
                get_client(), postal_codes=postal_codes, language_locale=language_locale
            )
        )

    @mcp.tool(tags={"read"}, annotations=_READ)
    def bulk_download(entities: list[str] | None = None) -> dict[str, Any]:
        """Export the account to a Bulk file; returns the result file URL when ready.

        Submits a Bulk download and polls to completion (the file can be large, so the URL is
        returned rather than the contents).

        Args:
            entities: Entity types to include, e.g. ["Campaigns", "AdGroups", "Ads", "Keywords"]
                (the default set).
        """
        return guarded(lambda: bulk.bulk_download(get_client(), entities=entities))
