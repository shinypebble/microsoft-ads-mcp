"""Read flows for campaigns, ad groups, keywords, ads, and budgets."""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.get_ad_groups_by_campaign_id_request import (
    GetAdGroupsByCampaignIdRequest,
)
from openapi_client.models.campaign.get_ads_by_ad_group_id_request import (
    GetAdsByAdGroupIdRequest,
)
from openapi_client.models.campaign.get_campaigns_by_account_id_request import (
    GetCampaignsByAccountIdRequest,
)
from openapi_client.models.campaign.get_campaigns_by_ids_request import (
    GetCampaignsByIdsRequest,
)
from openapi_client.models.campaign.get_keywords_by_ad_group_id_request import (
    GetKeywordsByAdGroupIdRequest,
)

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import (
    AdGroupSummary,
    AdSummary,
    CampaignSummary,
    KeywordSummary,
)
from . import as_list, first_attr

# Ad types we surface from get_ads (text-based search ads).
_AD_TYPES = ["ResponsiveSearch", "ExpandedText"]


def get_campaigns(client: MsAdsClient, *, include_deleted: bool = False) -> list[CampaignSummary]:
    resp = client.call(
        CAMPAIGN,
        "get_campaigns_by_account_id",
        # AdScheduleUseSearcherTimeZone is not returned by default; request it so the dayparting
        # time-zone context is visible (TimeZone / BiddingScheme come back without asking).
        GetCampaignsByAccountIdRequest(
            account_id=client.account_id,
            campaign_type="Search",
            return_additional_fields="AdScheduleUseSearcherTimeZone",
        ),
    )
    items = as_list(_unwrap(first_attr(resp, "Campaigns", "campaigns"), "Campaign", "campaign"))
    out = [CampaignSummary.from_sdk(c) for c in items]
    if not include_deleted:
        out = [c for c in out if c.status != "Deleted"]
    return out


def get_campaign_by_id(client: MsAdsClient, campaign_id: str) -> CampaignSummary | None:
    """Fetch a single campaign by id, or ``None`` if it does not exist.

    Mirrors ``get_campaigns``' request shape -- notably requesting AdScheduleUseSearcherTimeZone,
    which the API omits by default -- but reads just this campaign (GetCampaignsByIds) instead of
    listing the whole account to pull one campaign's context.
    """
    resp = client.call(
        CAMPAIGN,
        "get_campaigns_by_ids",
        GetCampaignsByIdsRequest(
            account_id=client.account_id,
            campaign_ids=[campaign_id],
            campaign_type="Search",
            return_additional_fields="AdScheduleUseSearcherTimeZone",
        ),
    )
    items = as_list(_unwrap(first_attr(resp, "Campaigns", "campaigns"), "Campaign", "campaign"))
    return CampaignSummary.from_sdk(items[0]) if items else None


def get_ad_groups(client: MsAdsClient, campaign_id: str) -> list[AdGroupSummary]:
    resp = client.call(
        CAMPAIGN,
        "get_ad_groups_by_campaign_id",
        GetAdGroupsByCampaignIdRequest(campaign_id=campaign_id),
    )
    items = as_list(_unwrap(first_attr(resp, "AdGroups", "ad_groups"), "AdGroup", "ad_group"))
    return [AdGroupSummary.from_sdk(ag) for ag in items]


def get_keywords(client: MsAdsClient, ad_group_id: str) -> list[KeywordSummary]:
    resp = client.call(
        CAMPAIGN,
        "get_keywords_by_ad_group_id",
        GetKeywordsByAdGroupIdRequest(ad_group_id=ad_group_id),
    )
    items = as_list(_unwrap(first_attr(resp, "Keywords", "keywords"), "Keyword", "keyword"))
    return [KeywordSummary.from_sdk(kw) for kw in items]


def get_ads(client: MsAdsClient, ad_group_id: str) -> list[AdSummary]:
    resp = client.call(
        CAMPAIGN,
        "get_ads_by_ad_group_id",
        GetAdsByAdGroupIdRequest(ad_group_id=ad_group_id, ad_types=_AD_TYPES),
    )
    items = as_list(_unwrap(first_attr(resp, "Ads", "ads"), "Ad", "ad"))
    return [AdSummary.from_sdk(ad) for ad in items]


def get_budgets(client: MsAdsClient) -> list[dict[str, Any]]:
    """Per-campaign budget view (shared budgets need their own ids; this reads campaigns)."""
    budgets = []
    for c in get_campaigns(client):
        budgets.append(
            {
                "campaign_id": c.id,
                "name": c.name,
                "daily_budget": c.daily_budget,
                "shared_budget_id": c.budget_id,
            }
        )
    return budgets


def _unwrap(value: Any, *keys: str) -> Any:
    if value is None:
        return None
    for key in keys:
        inner = getattr(value, key, None)
        if inner is not None:
            return inner
    return value
