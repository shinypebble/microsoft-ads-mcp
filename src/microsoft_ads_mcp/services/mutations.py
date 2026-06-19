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
from openapi_client.models.campaign.asset_link import AssetLink
from openapi_client.models.campaign.bid import Bid
from openapi_client.models.campaign.campaign import Campaign
from openapi_client.models.campaign.custom_parameter import CustomParameter
from openapi_client.models.campaign.custom_parameters import CustomParameters
from openapi_client.models.campaign.delete_ad_groups_request import DeleteAdGroupsRequest
from openapi_client.models.campaign.delete_ads_request import DeleteAdsRequest
from openapi_client.models.campaign.delete_campaigns_request import DeleteCampaignsRequest
from openapi_client.models.campaign.delete_keywords_request import DeleteKeywordsRequest
from openapi_client.models.campaign.get_campaigns_by_ids_request import GetCampaignsByIdsRequest
from openapi_client.models.campaign.keyword import Keyword
from openapi_client.models.campaign.responsive_search_ad import ResponsiveSearchAd
from openapi_client.models.campaign.text_asset import TextAsset
from openapi_client.models.campaign.update_ad_groups_request import UpdateAdGroupsRequest
from openapi_client.models.campaign.update_ads_request import UpdateAdsRequest
from openapi_client.models.campaign.update_campaigns_request import UpdateCampaignsRequest
from openapi_client.models.campaign.update_keywords_request import UpdateKeywordsRequest

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


def _present(**fields: Any) -> dict[str, Any]:
    """Keep only the fields the caller actually set.

    Partial updates send the id plus the changed fields only; the SDK serializes with
    ``exclude_none=True``, so an unset (``None``) field is omitted from the request entirely.
    Re-submitting a fully fetched entity makes the update endpoint reject round-tripped
    read-only fields (e.g. ``IsPolitical``), so we never do that.
    """
    return {k: v for k, v in fields.items() if v is not None}


def _validate_status(status: str | None) -> None:
    if status is not None and status not in ("Active", "Paused"):
        raise ValueError("status must be 'Active' or 'Paused'")


def _custom_parameters(params: dict[str, str] | None) -> CustomParameters | None:
    """Wrap a plain ``{key: value}`` dict as the SDK's ``UrlCustomParameters``.

    Keys are referenced in tracking templates / Final URL suffixes as ``{_key}``. Returns None
    for a missing/empty dict so the field is omitted from a partial update (left unchanged).
    """
    if not params:
        return None
    return CustomParameters(parameters=[CustomParameter(key=k, value=v) for k, v in params.items()])


def create_campaign(
    client: MsAdsClient,
    *,
    name: str,
    daily_budget: float,
    description: str = "",
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
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
        **_present(
            tracking_url_template=tracking_url_template,
            final_url_suffix=final_url_suffix,
            url_custom_parameters=_custom_parameters(url_custom_parameters),
        ),
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


def update_campaign_status(client: MsAdsClient, *, campaign_id: str, status: str) -> MutationResult:
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
    # Partial update: send only the id and new status. Re-submitting the full fetched campaign
    # makes the update endpoint reject round-tripped fields (e.g. IsPolitical) as invalid JSON.
    campaign = Campaign(id=campaign_id, status=status)
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
    client: MsAdsClient,
    *,
    campaign_id: str,
    name: str,
    cpc_bid: float = 1.0,
    language: str = "English",
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Create a paused ad group with a default CPC bid.

    ``language`` is required by Microsoft Advertising (error 1257
    ``CampaignServiceMissingLanguage`` otherwise); it defaults to English.
    """
    ad_group = AdGroup(
        name=name,
        status="Paused",
        cpc_bid=Bid(amount=cpc_bid),
        language=language,
        **_present(
            tracking_url_template=tracking_url_template,
            final_url_suffix=final_url_suffix,
            url_custom_parameters=_custom_parameters(url_custom_parameters),
        ),
    )
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
    ad_group_id: str,
    keywords: list[str],
    match_type: MatchType = "Broad",
    default_bid: float = 1.0,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Add keywords (active) with a default bid and match type.

    Any URL-tracking fields apply uniformly to every keyword in the batch.
    """
    url_fields = _present(
        tracking_url_template=tracking_url_template,
        final_url_suffix=final_url_suffix,
        url_custom_parameters=_custom_parameters(url_custom_parameters),
    )
    kw_models = [
        Keyword(
            text=text,
            match_type=match_type,
            status="Active",
            bid=Bid(amount=default_bid),
            **url_fields,
        )
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
    """Create a paused Responsive Search Ad (RSA)."""
    ad = ResponsiveSearchAd(
        type="ResponsiveSearch",
        status="Paused",
        final_urls=[final_url],
        headlines=[_asset_link(h[:30]) for h in headlines[:15]],
        descriptions=[_asset_link(d[:90]) for d in descriptions[:4]],
        **_present(
            tracking_url_template=tracking_url_template,
            final_url_suffix=final_url_suffix,
            url_custom_parameters=_custom_parameters(url_custom_parameters),
        ),
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


def update_campaign(
    client: MsAdsClient,
    *,
    campaign_id: str,
    name: str | None = None,
    daily_budget: float | None = None,
    status: str | None = None,
    bid_strategy_id: str | None = None,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Update an existing campaign in place; only the fields you pass change."""
    _validate_status(status)
    campaign = Campaign(
        id=campaign_id,
        **_present(
            name=name,
            daily_budget=daily_budget,
            status=status,
            bid_strategy_id=bid_strategy_id,
            tracking_url_template=tracking_url_template,
            final_url_suffix=final_url_suffix,
            url_custom_parameters=_custom_parameters(url_custom_parameters),
        ),
    )
    resp = client.call(
        CAMPAIGN,
        "update_campaigns",
        UpdateCampaignsRequest(account_id=client.account_id, campaigns=[campaign]),
    )
    errors = _partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"Campaign {campaign_id} updated" if not errors else "Update failed",
        ids=[str(campaign_id)],
        partial_errors=errors,
    )


def update_ad_group(
    client: MsAdsClient,
    *,
    campaign_id: str,
    ad_group_id: str,
    name: str | None = None,
    status: str | None = None,
    cpc_bid: float | None = None,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Update an existing ad group in place (Microsoft requires the parent ``campaign_id``)."""
    _validate_status(status)
    fields = _present(
        name=name,
        status=status,
        tracking_url_template=tracking_url_template,
        final_url_suffix=final_url_suffix,
        url_custom_parameters=_custom_parameters(url_custom_parameters),
    )
    if cpc_bid is not None:
        fields["cpc_bid"] = Bid(amount=cpc_bid)
    ad_group = AdGroup(id=ad_group_id, **fields)
    resp = client.call(
        CAMPAIGN,
        "update_ad_groups",
        UpdateAdGroupsRequest(campaign_id=campaign_id, ad_groups=[ad_group]),
    )
    errors = _partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"Ad group {ad_group_id} updated" if not errors else "Update failed",
        ids=[str(ad_group_id)],
        partial_errors=errors,
    )


def update_responsive_search_ad(
    client: MsAdsClient,
    *,
    ad_group_id: str,
    ad_id: str,
    final_url: str | None = None,
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
    path1: str | None = None,
    path2: str | None = None,
    status: str | None = None,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Repoint/refresh an existing RSA in place; only the fields you pass change.

    ``final_url`` is re-sent as a single-item list, and the ``ResponsiveSearch`` type
    discriminator is required so the polymorphic update can dispatch.
    """
    _validate_status(status)
    fields = _present(
        status=status,
        path1=path1[:15] if path1 is not None else None,
        path2=path2[:15] if path2 is not None else None,
        tracking_url_template=tracking_url_template,
        final_url_suffix=final_url_suffix,
        url_custom_parameters=_custom_parameters(url_custom_parameters),
    )
    if final_url is not None:
        fields["final_urls"] = [final_url]
    if headlines is not None:
        fields["headlines"] = [_asset_link(h[:30]) for h in headlines[:15]]
    if descriptions is not None:
        fields["descriptions"] = [_asset_link(d[:90]) for d in descriptions[:4]]
    ad = ResponsiveSearchAd(id=ad_id, type="ResponsiveSearch", **fields)
    resp = client.call(CAMPAIGN, "update_ads", UpdateAdsRequest(ad_group_id=ad_group_id, ads=[ad]))
    errors = _partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"Ad {ad_id} updated" if not errors else "Update failed",
        ids=[str(ad_id)],
        partial_errors=errors,
    )


def update_keyword(
    client: MsAdsClient,
    *,
    ad_group_id: str,
    keyword_id: str,
    bid: float | None = None,
    match_type: MatchType | None = None,
    status: str | None = None,
    final_url: str | None = None,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Update an existing keyword in place (bid, match type, status, or URL fields)."""
    _validate_status(status)
    fields: dict[str, Any] = _present(
        match_type=match_type,
        status=status,
        tracking_url_template=tracking_url_template,
        final_url_suffix=final_url_suffix,
        url_custom_parameters=_custom_parameters(url_custom_parameters),
    )
    if bid is not None:
        fields["bid"] = Bid(amount=bid)
    if final_url is not None:
        fields["final_urls"] = [final_url]
    keyword = Keyword(id=keyword_id, **fields)
    resp = client.call(
        CAMPAIGN,
        "update_keywords",
        UpdateKeywordsRequest(ad_group_id=ad_group_id, keywords=[keyword]),
    )
    errors = _partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"Keyword {keyword_id} updated" if not errors else "Update failed",
        ids=[str(keyword_id)],
        partial_errors=errors,
    )


def delete_campaigns(client: MsAdsClient, *, campaign_ids: list[str]) -> MutationResult:
    """Delete campaigns by id."""
    resp = client.call(
        CAMPAIGN,
        "delete_campaigns",
        DeleteCampaignsRequest(account_id=client.account_id, campaign_ids=campaign_ids),
    )
    return _delete_result(resp, campaign_ids, "campaign")


def delete_ad_groups(
    client: MsAdsClient, *, campaign_id: str, ad_group_ids: list[str]
) -> MutationResult:
    """Delete ad groups by id (within their parent campaign)."""
    resp = client.call(
        CAMPAIGN,
        "delete_ad_groups",
        DeleteAdGroupsRequest(campaign_id=campaign_id, ad_group_ids=ad_group_ids),
    )
    return _delete_result(resp, ad_group_ids, "ad group")


def delete_ads(client: MsAdsClient, *, ad_group_id: str, ad_ids: list[str]) -> MutationResult:
    """Delete ads by id (within their parent ad group)."""
    resp = client.call(
        CAMPAIGN, "delete_ads", DeleteAdsRequest(ad_group_id=ad_group_id, ad_ids=ad_ids)
    )
    return _delete_result(resp, ad_ids, "ad")


def delete_keywords(
    client: MsAdsClient, *, ad_group_id: str, keyword_ids: list[str]
) -> MutationResult:
    """Delete keywords by id (within their parent ad group)."""
    resp = client.call(
        CAMPAIGN,
        "delete_keywords",
        DeleteKeywordsRequest(ad_group_id=ad_group_id, keyword_ids=keyword_ids),
    )
    return _delete_result(resp, keyword_ids, "keyword")


def _delete_result(resp: Any, ids: list[str], label: str) -> MutationResult:
    """Delete responses carry only PartialErrors; success is the absence of errors."""
    errors = _partial_errors(resp)
    n = len(ids)
    return MutationResult(
        ok=not errors,
        message=f"Deleted {n} {label}{'s' if n != 1 else ''}" if not errors else "Delete failed",
        ids=[str(i) for i in ids],
        partial_errors=errors,
    )


def _asset_link(text: str) -> AssetLink:
    """An AssetLink carrying a TextAsset.

    Build it as a model (not a dict) so the polymorphic ``Asset`` keeps its ``TextAsset``
    subtype; a plain dict deserializes into the base ``Asset`` and fails to serialize.
    """
    return AssetLink(asset=TextAsset(type="TextAsset", text=text))


def _unwrap(value: Any, *keys: str) -> Any:
    if value is None:
        return None
    for key in keys:
        inner = getattr(value, key, None)
        if inner is not None:
            return inner
    return value
