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
from openapi_client.models.campaign.bidding_scheme import BiddingScheme
from openapi_client.models.campaign.campaign import Campaign
from openapi_client.models.campaign.custom_parameter import CustomParameter
from openapi_client.models.campaign.custom_parameters import CustomParameters
from openapi_client.models.campaign.delete_ad_groups_request import DeleteAdGroupsRequest
from openapi_client.models.campaign.delete_ads_request import DeleteAdsRequest
from openapi_client.models.campaign.delete_campaigns_request import DeleteCampaignsRequest
from openapi_client.models.campaign.delete_keywords_request import DeleteKeywordsRequest
from openapi_client.models.campaign.enhanced_cpc_bidding_scheme import EnhancedCpcBiddingScheme
from openapi_client.models.campaign.get_campaigns_by_ids_request import GetCampaignsByIdsRequest
from openapi_client.models.campaign.keyword import Keyword
from openapi_client.models.campaign.manual_cpc_bidding_scheme import ManualCpcBiddingScheme
from openapi_client.models.campaign.max_clicks_bidding_scheme import MaxClicksBiddingScheme
from openapi_client.models.campaign.max_conversion_value_bidding_scheme import (
    MaxConversionValueBiddingScheme,
)
from openapi_client.models.campaign.max_conversions_bidding_scheme import (
    MaxConversionsBiddingScheme,
)
from openapi_client.models.campaign.responsive_search_ad import ResponsiveSearchAd
from openapi_client.models.campaign.target_cpa_bidding_scheme import TargetCpaBiddingScheme
from openapi_client.models.campaign.target_roas_bidding_scheme import TargetRoasBiddingScheme
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


def _validate_network(network: str | None) -> None:
    # Only the two networks Microsoft's UI offers for Search ad groups are settable;
    # "SyndicatedSearchOnly" / "InHousePromotion" are rejected (CampaignServiceInvalidNetwork).
    if network is not None and network not in (
        "OwnedAndOperatedAndSyndicatedSearch",
        "OwnedAndOperatedOnly",
    ):
        raise ValueError(
            "network must be 'OwnedAndOperatedAndSyndicatedSearch' or 'OwnedAndOperatedOnly'"
        )


# A campaign's inline bid strategy (BiddingScheme) keyed by friendly type, paired with the optional
# knobs that scheme accepts. The SDK subclass stamps the right BiddingScheme.Type itself, so we just
# instantiate it. `max_cpc` is a Bid(amount=...); `target_cpa` / `target_roas` are plain floats.
_BIDDING_SCHEMES: dict[str, tuple[type[BiddingScheme], tuple[str, ...]]] = {
    "EnhancedCpc": (EnhancedCpcBiddingScheme, ()),
    "ManualCpc": (ManualCpcBiddingScheme, ()),
    "MaxClicks": (MaxClicksBiddingScheme, ("max_cpc",)),
    "MaxConversions": (MaxConversionsBiddingScheme, ("max_cpc", "target_cpa")),
    "TargetCpa": (TargetCpaBiddingScheme, ("max_cpc", "target_cpa")),
    "MaxConversionValue": (MaxConversionValueBiddingScheme, ("max_cpc", "target_roas")),
    "TargetRoas": (TargetRoasBiddingScheme, ("max_cpc", "target_roas")),
}


def _bidding_scheme(
    bid_strategy_type: str | None,
    *,
    max_cpc: float | None = None,
    target_cpa: float | None = None,
    target_roas: float | None = None,
) -> BiddingScheme | None:
    """Build a campaign's inline ``BiddingScheme`` from a friendly type plus optional knobs.

    Returns None when no type is given, so the field is omitted from a partial update. Each knob is
    only valid on the schemes that use it (see ``_BIDDING_SCHEMES``); TargetCpa / TargetRoas usually
    need their target set, but that's left to Microsoft to enforce so a clean partial error surfaces
    rather than a guess. ``get_campaigns`` returns the long ``*BiddingScheme`` discriminator for
    TargetRoas / MaxConversionValue, so we accept that form too (strip the suffix) to round-trip.
    """
    knobs = {"max_cpc": max_cpc, "target_cpa": target_cpa, "target_roas": target_roas}
    if bid_strategy_type is None:
        set_knobs = [name for name, value in knobs.items() if value is not None]
        if set_knobs:
            raise ValueError(f"bid_strategy_type is required when setting {', '.join(set_knobs)}")
        return None
    key = bid_strategy_type.removesuffix("BiddingScheme") or bid_strategy_type
    entry = _BIDDING_SCHEMES.get(key)
    if entry is None:
        raise ValueError(
            "bid_strategy_type must be one of "
            + ", ".join(_BIDDING_SCHEMES)
            + f" (got {bid_strategy_type!r})"
        )
    cls, allowed = entry
    for name, value in knobs.items():
        if value is not None and name not in allowed:
            raise ValueError(
                f"{name} is not valid for bid_strategy_type {key!r} "
                f"(accepts: {', '.join(allowed) or 'no parameters'})"
            )
    kwargs: dict[str, Any] = {}
    if "max_cpc" in allowed and max_cpc is not None:
        kwargs["max_cpc"] = Bid(amount=max_cpc)
    if "target_cpa" in allowed and target_cpa is not None:
        kwargs["target_cpa"] = target_cpa
    if "target_roas" in allowed and target_roas is not None:
        kwargs["target_roas"] = target_roas
    return cls(**kwargs)


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
    bid_strategy_type: str | None = None,
    max_cpc: float | None = None,
    target_cpa: float | None = None,
    target_roas: float | None = None,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Create a paused Search campaign with a daily budget."""
    bidding_scheme = _bidding_scheme(
        bid_strategy_type, max_cpc=max_cpc, target_cpa=target_cpa, target_roas=target_roas
    )
    campaign = Campaign(
        name=name,
        description=description or name,
        budget_type="DailyBudgetStandard",
        daily_budget=daily_budget,
        status="Paused",
        time_zone="EasternTimeUSCanada",
        campaign_type="Search",
        **_present(
            bidding_scheme=bidding_scheme,
            tracking_url_template=tracking_url_template,
            final_url_suffix=final_url_suffix,
            url_custom_parameters=_custom_parameters(url_custom_parameters),
        ),
    )
    # call_raw: a rejected campaign returns CampaignIds=[null] + PartialErrors, which the typed
    # model can't parse (its id list is non-nullable strings); the raw dict surfaces it.
    resp = client.call_raw(
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
    network: str | None = None,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Create a paused ad group with a default CPC bid.

    ``language`` is required by Microsoft Advertising (error 1257
    ``CampaignServiceMissingLanguage`` otherwise); it defaults to English.
    """
    _validate_network(network)
    ad_group = AdGroup(
        name=name,
        status="Paused",
        cpc_bid=Bid(amount=cpc_bid),
        language=language,
        **_present(
            network=network,
            tracking_url_template=tracking_url_template,
            final_url_suffix=final_url_suffix,
            url_custom_parameters=_custom_parameters(url_custom_parameters),
        ),
    )
    # call_raw: a rejected ad group returns AdGroupIds=[null] + PartialErrors, which the typed
    # model can't parse (its id list is non-nullable strings); the raw dict surfaces it.
    resp = client.call_raw(
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
    # call_raw: a rejected keyword (e.g. a duplicate) returns KeywordIds=[null] + PartialErrors,
    # which the typed model can't parse (its id list is non-nullable strings); the raw dict
    # surfaces the reason instead of crashing.
    resp = client.call_raw(
        CAMPAIGN,
        "add_keywords",
        AddKeywordsRequest(ad_group_id=ad_group_id, keywords=kw_models),
    )
    ids = _ids(resp, "KeywordIds", "keyword_ids")
    errors = _partial_errors(resp)
    return MutationResult(
        ok=bool(ids),
        message=(
            f"Added {len(ids)} keyword(s) to ad group {ad_group_id}"
            if ids
            else "Add keywords failed"
        ),
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
    headline_links, err = _prepare_headlines(headlines)
    if err is not None:
        return MutationResult(ok=False, message="RSA create failed", partial_errors=[err])
    ad = ResponsiveSearchAd(
        type="ResponsiveSearch",
        status="Paused",
        final_urls=[final_url],
        headlines=headline_links,
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
    # call_raw: a rejected ad returns AdIds=[null] + PartialErrors, which the typed model can't
    # parse (its id list is non-nullable strings); the raw dict surfaces the reason.
    resp = client.call_raw(CAMPAIGN, "add_ads", AddAdsRequest(ad_group_id=ad_group_id, ads=[ad]))
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
    bid_strategy_type: str | None = None,
    max_cpc: float | None = None,
    target_cpa: float | None = None,
    target_roas: float | None = None,
    time_zone: str | None = None,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Update an existing campaign in place; only the fields you pass change."""
    _validate_status(status)
    if bid_strategy_id is not None and bid_strategy_type is not None:
        raise ValueError(
            "set either bid_strategy_id (a portfolio strategy) or bid_strategy_type "
            "(the campaign's own inline scheme), not both"
        )
    bidding_scheme = _bidding_scheme(
        bid_strategy_type, max_cpc=max_cpc, target_cpa=target_cpa, target_roas=target_roas
    )
    campaign = Campaign(
        id=campaign_id,
        **_present(
            name=name,
            daily_budget=daily_budget,
            status=status,
            bid_strategy_id=bid_strategy_id,
            bidding_scheme=bidding_scheme,
            time_zone=time_zone,
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
    network: str | None = None,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    url_custom_parameters: dict[str, str] | None = None,
) -> MutationResult:
    """Update an existing ad group in place (Microsoft requires the parent ``campaign_id``)."""
    _validate_status(status)
    _validate_network(network)
    fields = _present(
        name=name,
        status=status,
        network=network,
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
        headline_links, err = _prepare_headlines(headlines)
        if err is not None:
            return MutationResult(
                ok=False, message="Update failed", ids=[str(ad_id)], partial_errors=[err]
            )
        fields["headlines"] = headline_links
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


# Delete error codes that mean "the entity is already gone" -- an already-Deleted entity
# (CampaignServiceInvalid*Status) or one that never existed (...DoesNotExist). Deleting something
# that is already deleted is the caller's intent, so we treat these as a no-op success rather than a
# failure. Seeded from the documented campaign code; the ...DoesNotExist suffix below catches the
# per-entity not-found codes generically. Widen this set if the live API reports other codes.
_IDEMPOTENT_DELETE_CODES = frozenset(
    {
        "CampaignServiceInvalidCampaignStatus",
        "CampaignServiceInvalidAdGroupStatus",
        "CampaignServiceInvalidAdStatus",
        "CampaignServiceInvalidKeywordStatus",
    }
)


def _is_idempotent_delete_error(error: str) -> bool:
    """True when a delete partial error means the entity is already gone (safe to ignore)."""
    code = error.split(":", 1)[0].strip()
    return code in _IDEMPOTENT_DELETE_CODES or code.endswith("DoesNotExist")


def _delete_result(resp: Any, ids: list[str], label: str) -> MutationResult:
    """Delete responses carry only PartialErrors; success is the absence of *real* errors.

    Deletes are idempotent: an "already deleted / does not exist" partial error is treated as a
    no-op (the entity is gone, which is what the caller wanted) instead of a failure, so re-running
    a delete -- or deleting an already-``Deleted`` campaign -- returns ``ok`` rather than leaking a
    raw ``CampaignServiceInvalidCampaignStatus``.
    """
    real_errors = [e for e in _partial_errors(resp) if not _is_idempotent_delete_error(e)]
    already_gone = [e for e in _partial_errors(resp) if _is_idempotent_delete_error(e)]
    if real_errors:
        return MutationResult(
            ok=False, message="Delete failed", ids=[str(i) for i in ids], partial_errors=real_errors
        )
    n = len(ids)
    note = f" ({len(already_gone)} already deleted/not found)" if already_gone else ""
    return MutationResult(
        ok=True,
        message=f"Deleted {n} {label}{'s' if n != 1 else ''}{note}",
        ids=[str(i) for i in ids],
        partial_errors=[],
    )


def _asset_link(text: str) -> AssetLink:
    """An AssetLink carrying a TextAsset.

    Build it as a model (not a dict) so the polymorphic ``Asset`` keeps its ``TextAsset``
    subtype; a plain dict deserializes into the base ``Asset`` and fails to serialize.
    """
    return AssetLink(asset=TextAsset(type="TextAsset", text=text))


def _balanced_braces(text: str) -> bool:
    """True when ``{``/``}`` are balanced and never close before they open (DKI doesn't nest)."""
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _truncate_headline(text: str) -> str:
    """Cap a headline at 30 chars, but never truncate inside a dynamic-text function.

    A headline may embed a keyword-insertion / customizer function like ``{KeyWord:Default Text}``.
    The 30-char display limit applies to the *rendered* text, not the literal markup (which
    Microsoft validates itself), so blindly slicing the literal to 30 chars would chop the closing
    brace and corrupt the function (-> ``InvalidFunctionFormat``). When the headline contains a
    function (any ``{``), pass it through untouched; otherwise apply the plain 30-char cap.
    """
    return text if "{" in text else text[:30]


def _prepare_headlines(headlines: list[str]) -> tuple[list[AssetLink] | None, str | None]:
    """Validate and DKI-aware-truncate up to 15 headlines into AssetLinks.

    Returns ``(asset_links, None)`` on success, or ``(None, message)`` naming the first headline
    whose dynamic-text braces are unbalanced -- so the caller can return a clear ``ok=false``
    instead of passing corrupted markup through to Bing's opaque ``InvalidFunctionFormat``.
    """
    selected = headlines[:15]
    for h in selected:
        if not _balanced_braces(h):
            return None, f"Headline has unbalanced {{ }} braces (check dynamic-text syntax): {h!r}"
    return [_asset_link(_truncate_headline(h)) for h in selected], None


def _unwrap(value: Any, *keys: str) -> Any:
    if value is None:
        return None
    for key in keys:
        inner = getattr(value, key, None)
        if inner is not None:
            return inner
    return value
