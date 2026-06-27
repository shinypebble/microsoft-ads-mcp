"""Website-exclusion (negative-site) flows: list, add, and remove campaign-level blocked sites.

These block where ads serve -- specific websites and/or mobile-app ids ("referrer domains") -- at
the campaign level. Microsoft's ``SetNegativeSitesToCampaigns`` has *replace-all* semantics: it
overwrites the campaign's entire negative-site list. To avoid clobbering existing exclusions,
``add`` and ``remove`` are read-modify-write: read the current list, merge or filter, then set it
back. The
list is plain URL strings (no per-site id), so removal is by URL, not id. The set response carries
only flat ``PartialErrors`` and no ids, so a plain ``client.call`` is enough (no ``call_raw``); the
API is the authority on what's a valid site (e.g. Microsoft sites like MSN.com can't be excluded;
there's a ~2500-site/campaign cap), and those rejections surface as ``partial_errors``.
"""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.campaign_negative_sites import CampaignNegativeSites
from openapi_client.models.campaign.get_negative_sites_by_campaign_ids_request import (
    GetNegativeSitesByCampaignIdsRequest,
)
from openapi_client.models.campaign.set_negative_sites_to_campaigns_request import (
    SetNegativeSitesToCampaignsRequest,
)

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import MutationResult, WebsiteExclusionSummary
from . import as_list, first_attr, flat_partial_errors


def _normalize_sites(urls: list[str]) -> list[str]:
    """Trim whitespace, drop a leading http(s):// scheme, drop empties, dedupe (case-insensitive).

    Microsoft wants bare domains/paths (or mobile-app ids), not full URLs. Validation is kept light
    on purpose -- the API decides what's a valid site and reports rejections as partial errors.
    Order is preserved; the first spelling of a case-insensitive duplicate wins.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        site = raw.strip()
        for scheme in ("https://", "http://"):
            if site.lower().startswith(scheme):
                site = site[len(scheme) :]
                break
        if not site:
            continue
        key = site.lower()
        if key not in seen:
            seen.add(key)
            out.append(site)
    return out


def _read_sites(client: MsAdsClient, campaign_id: str) -> list[str]:
    """Return the campaign's current negative-site URLs (empty list if none)."""
    resp = client.call(
        CAMPAIGN,
        "get_negative_sites_by_campaign_ids",
        GetNegativeSitesByCampaignIdsRequest(
            account_id=client.account_id, campaign_ids=[campaign_id]
        ),
    )
    entries = as_list(first_attr(resp, "CampaignNegativeSites", "campaign_negative_sites"))
    chosen: Any = None
    for entry in entries:
        if entry is None:
            continue
        if str(first_attr(entry, "CampaignId", "campaign_id")) == str(campaign_id):
            chosen = entry
            break
        if chosen is None:
            chosen = entry
    if chosen is None:
        # No entry for this campaign. If Microsoft reported it in PartialErrors (e.g. an invalid or
        # inaccessible campaign id), surface that instead of masquerading as "no sites blocked".
        errors = flat_partial_errors(resp)
        if errors:
            raise ValueError(
                f"Could not read website exclusions for campaign {campaign_id}: "
                + "; ".join(errors)
            )
        return []
    return [str(s) for s in as_list(first_attr(chosen, "NegativeSites", "negative_sites"))]


def _set_sites(client: MsAdsClient, campaign_id: str, sites: list[str]) -> list[str]:
    """Replace the campaign's negative-site list with ``sites``; return partial-error messages."""
    resp = client.call(
        CAMPAIGN,
        "set_negative_sites_to_campaigns",
        SetNegativeSitesToCampaignsRequest(
            account_id=client.account_id,
            campaign_negative_sites=[
                CampaignNegativeSites(campaign_id=campaign_id, negative_sites=sites)
            ],
        ),
    )
    return flat_partial_errors(resp)


def get_website_exclusions(client: MsAdsClient, *, campaign_id: str) -> WebsiteExclusionSummary:
    """List the website / mobile-app-id exclusions (negative sites) blocked on a campaign."""
    urls = _read_sites(client, campaign_id)
    return WebsiteExclusionSummary(campaign_id=str(campaign_id), urls=urls, count=len(urls))


def add_website_exclusions(
    client: MsAdsClient, *, campaign_id: str, urls: list[str]
) -> MutationResult:
    """Block referrer domains / mobile-app ids on a campaign (additive read-modify-write merge)."""
    new_sites = _normalize_sites(urls)
    if not new_sites:
        raise ValueError("urls must contain at least one non-empty site")
    existing = _read_sites(client, campaign_id)
    merged = _normalize_sites([*existing, *new_sites])
    errors = _set_sites(client, campaign_id, merged)
    return MutationResult(
        ok=not errors,
        message=(
            f"Blocked {len(new_sites)} site(s) on campaign {campaign_id}"
            if not errors
            else "Add website exclusions failed"
        ),
        ids=new_sites,
        partial_errors=errors,
    )


def remove_website_exclusions(
    client: MsAdsClient, *, campaign_id: str, urls: list[str]
) -> MutationResult:
    """Unblock referrer domains / app ids on a campaign (read-modify-write, matched by URL)."""
    drop = _normalize_sites(urls)
    if not drop:
        raise ValueError("urls must contain at least one non-empty site")
    drop_keys = {s.lower() for s in drop}
    existing = _read_sites(client, campaign_id)
    kept = [s for s in existing if s.lower() not in drop_keys]
    errors = _set_sites(client, campaign_id, kept)
    return MutationResult(
        ok=not errors,
        message=(
            f"Unblocked {len(existing) - len(kept)} site(s) on campaign {campaign_id}"
            if not errors
            else "Remove website exclusions failed"
        ),
        ids=drop,
        partial_errors=errors,
    )
