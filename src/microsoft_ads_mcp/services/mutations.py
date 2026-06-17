"""Write flows: create campaigns/ad groups/keywords/ads and change campaign status.

New entities are created **paused** by default, matching the original server's safety stance:
an agent should never silently start spending.
"""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.ad_group import AdGroup
from openapi_client.models.campaign.add_ad_groups_request import AddAdGroupsRequest
from openapi_client.models.campaign.add_ads_request import AddAdsRequest
from openapi_client.models.campaign.add_campaigns_request import AddCampaignsRequest
from openapi_client.models.campaign.add_keywords_request import AddKeywordsRequest
from openapi_client.models.campaign.bid import Bid
from openapi_client.models.campaign.campaign import Campaign
from openapi_client.models.campaign.get_campaigns_by_ids_request import GetCampaignsByIdsRequest
from openapi_client.models.campaign.keyword import Keyword
from openapi_client.models.campaign.responsive_search_ad import ResponsiveSearchAd
from openapi_client.models.campaign.text_asset import TextAsset
from openapi_client.models.campaign.update_campaigns_request import UpdateCampaignsRequest

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import MatchType, MutationResult
from . import as_list, first_attr


def _partial_errors(resp: Any) -> list[str]:
    raw = first_attr(resp, "PartialErrors", "partial_errors")
    out: list[str] = []
    for err in as_list(_unwrap(raw, "BatchError", "batch_error")):
        msg = first_attr(err, "Message", "message", default="")
        code = first_attr(err, "ErrorCode", "error_code", "Code", "code", default="")
        out.append(f"{code}: {msg}".strip(": "))
    return out


def _ids(resp: Any, *names: str) -> list[str]:
    raw = first_attr(resp, *names)
    items = as_list(_unwrap(raw, "long"))
    return [str(i) for i in items if i is not None]


def create_campaign(
    client: MsAdsClient, *, name: str, daily_budget: float, description: str = ""
) -> MutationResult:
    """Create a paused Search campaign with a daily budget."""
    campaign = Campaign(
        name=name,
        description=description or name,
        budget_type="DailyBudgetStandard",
        daily_budget=daily_budget,
        status="Paused",
        time_zone="EasternTimeUSCanada",
        campaign_type="Search",
    )
    resp = client.call(
        CAMPAIGN,
        "add_campaigns",
        AddCampaignsRequest(account_id=client.account_id, campaigns=[campaign]),
    )
    ids = _ids(resp, "CampaignIds", "campaign_ids")
    errors = _partial_errors(resp)
    return MutationResult(
        ok=bool(ids),
        message=(
            f"Campaign '{name}' created (PAUSED), id {ids[0]}, ${daily_budget:g}/day"
            if ids
            else "Campaign create failed"
        ),
        ids=ids,
        partial_errors=errors,
    )


def update_campaign_status(client: MsAdsClient, *, campaign_id: int, status: str) -> MutationResult:
    """Set a campaign to Active or Paused (reads the campaign, then updates status)."""
    if status not in ("Active", "Paused"):
        raise ValueError("status must be 'Active' or 'Paused'")
    got = client.call(
        CAMPAIGN,
        "get_campaigns_by_ids",
        GetCampaignsByIdsRequest(
            account_id=client.account_id, campaign_ids=[campaign_id], campaign_type="Search"
        ),
    )
    campaigns = as_list(_unwrap(first_attr(got, "Campaigns", "campaigns"), "Campaign", "campaign"))
    if not campaigns:
        return MutationResult(ok=False, message=f"Campaign {campaign_id} not found")
    campaign = campaigns[0]
    campaign.Status = status
    resp = client.call(
        CAMPAIGN,
        "update_campaigns",
        UpdateCampaignsRequest(account_id=client.account_id, campaigns=[campaign]),
    )
    errors = _partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"Campaign {campaign_id} set to {status}" if not errors else "Update failed",
        ids=[str(campaign_id)],
        partial_errors=errors,
    )


def create_ad_group(
    client: MsAdsClient, *, campaign_id: int, name: str, cpc_bid: float = 1.0
) -> MutationResult:
    """Create a paused ad group with a default CPC bid."""
    ad_group = AdGroup(name=name, status="Paused", cpc_bid=Bid(amount=cpc_bid))
    resp = client.call(
        CAMPAIGN,
        "add_ad_groups",
        AddAdGroupsRequest(
            campaign_id=campaign_id,
            ad_groups=[ad_group],
            return_inherited_bid_strategy_types=False,
        ),
    )
    ids = _ids(resp, "AdGroupIds", "ad_group_ids")
    errors = _partial_errors(resp)
    return MutationResult(
        ok=bool(ids),
        message=f"Ad group '{name}' created, id {ids[0]}" if ids else "Ad group create failed",
        ids=ids,
        partial_errors=errors,
    )


def add_keywords(
    client: MsAdsClient,
    *,
    ad_group_id: int,
    keywords: list[str],
    match_type: MatchType = "Broad",
    default_bid: float = 1.0,
) -> MutationResult:
    """Add keywords (active) with a default bid and match type."""
    kw_models = [
        Keyword(text=text, match_type=match_type, status="Active", bid=Bid(amount=default_bid))
        for text in keywords
    ]
    resp = client.call(
        CAMPAIGN,
        "add_keywords",
        AddKeywordsRequest(ad_group_id=ad_group_id, keywords=kw_models),
    )
    ids = _ids(resp, "KeywordIds", "keyword_ids")
    errors = _partial_errors(resp)
    return MutationResult(
        ok=bool(ids),
        message=f"Added {len(ids)} keyword(s) to ad group {ad_group_id}",
        ids=ids,
        partial_errors=errors,
    )


def create_responsive_search_ad(
    client: MsAdsClient,
    *,
    ad_group_id: int,
    final_url: str,
    headlines: list[str],
    descriptions: list[str],
    path1: str = "",
    path2: str = "",
) -> MutationResult:
    """Create a paused Responsive Search Ad (RSA)."""
    ad = ResponsiveSearchAd(
        type="ResponsiveSearch",
        status="Paused",
        final_urls=[final_url],
        headlines=[_asset_link(h[:30]) for h in headlines[:15]],
        descriptions=[_asset_link(d[:90]) for d in descriptions[:4]],
    )
    if path1:
        ad.Path1 = path1[:15]
    if path2:
        ad.Path2 = path2[:15]
    resp = client.call(CAMPAIGN, "add_ads", AddAdsRequest(ad_group_id=ad_group_id, ads=[ad]))
    ids = _ids(resp, "AdIds", "ad_ids")
    errors = _partial_errors(resp)
    return MutationResult(
        ok=bool(ids),
        message=(
            f"RSA created (PAUSED), id {ids[0]}: {len(headlines)} headlines / "
            f"{len(descriptions)} descriptions"
            if ids
            else "RSA create failed"
        ),
        ids=ids,
        partial_errors=errors,
    )


def _asset_link(text: str) -> dict[str, Any]:
    """An AssetLink carrying a TextAsset. The SDK accepts a dict for the polymorphic asset."""
    return {"Asset": TextAsset(type="Text", text=text).to_dict()}


def _unwrap(value: Any, *keys: str) -> Any:
    if value is None:
        return None
    for key in keys:
        inner = getattr(value, key, None)
        if inner is not None:
            return inner
    return value
