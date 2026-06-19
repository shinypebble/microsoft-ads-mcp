"""Ad Insight (keyword research): first-page bid estimates, keyword ideas, traffic estimates.

These read from Microsoft's Ad Insight service -- the programmatic side of the Keyword Planner,
a separate REST service from Campaign Management. Everything here is a *modeled estimate*: it is
account-scoped, and Microsoft returns null for keywords or match types it has no data for.

The three flows map onto:
  * ``GetEstimatedBidByKeywords`` -- the bid to reach a target position (FirstPage / MainLine).
  * ``GetKeywordIdeas`` -- keyword discovery with demand + competition signals.
  * ``GetKeywordTrafficEstimates`` -- weekly clicks/impressions/cost for a keyword at a given bid.
"""

from __future__ import annotations

from typing import Any

from openapi_client.models.adinsight.ad_group_estimator import AdGroupEstimator
from openapi_client.models.adinsight.campaign_estimator import CampaignEstimator
from openapi_client.models.adinsight.get_estimated_bid_by_keywords_request import (
    GetEstimatedBidByKeywordsRequest,
)
from openapi_client.models.adinsight.get_keyword_ideas_request import GetKeywordIdeasRequest
from openapi_client.models.adinsight.get_keyword_traffic_estimates_request import (
    GetKeywordTrafficEstimatesRequest,
)
from openapi_client.models.adinsight.keyword import Keyword
from openapi_client.models.adinsight.keyword_and_match_type import KeywordAndMatchType
from openapi_client.models.adinsight.keyword_estimator import KeywordEstimator
from openapi_client.models.adinsight.language_criterion import LanguageCriterion
from openapi_client.models.adinsight.language_search_parameter import LanguageSearchParameter
from openapi_client.models.adinsight.location_criterion import LocationCriterion
from openapi_client.models.adinsight.location_search_parameter import LocationSearchParameter
from openapi_client.models.adinsight.network_criterion import NetworkCriterion
from openapi_client.models.adinsight.network_search_parameter import NetworkSearchParameter
from openapi_client.models.adinsight.query_search_parameter import QuerySearchParameter
from openapi_client.models.adinsight.url_search_parameter import UrlSearchParameter

from ..api.client import AD_INSIGHT, MsAdsClient
from ..domain.entities import (
    BidEstimate,
    FirstPageBidCheck,
    FirstPageBidReport,
    KeywordBidEstimate,
    KeywordIdeaSummary,
    KeywordSummary,
    KeywordTrafficEstimate,
)
from . import as_list, campaigns, first_attr

# Where ads can land; the bid estimate is "the bid to reach this position".
TARGET_POSITIONS = ("FirstPage", "MainLine", "MainLine1")
# Match types we accept (the API also defines "Aggregate", which we don't surface here).
MATCH_TYPES = ("Broad", "Phrase", "Exact")

# GetKeywordIdeas requires a language, at least one location, and a network. These defaults make
# the tool work out of the box for a US/English advertiser; callers override as needed.
DEFAULT_LANGUAGE = "English"
UNITED_STATES_LOCATION_ID = "190"
DEFAULT_NETWORK = "OwnedAndOperatedAndSyndicatedSearch"
# Which columns GetKeywordIdeas should populate. We skip the account-context attributes
# (AdGroupId/AdGroupName/AdImpressionShare) that only apply when seeding from an existing account.
_IDEA_ATTRIBUTES = [
    "Keyword",
    "Source",
    "MonthlySearchCounts",
    "SuggestedBid",
    "Competition",
    "Relevance",
]


def estimate_keyword_bids(
    client: MsAdsClient,
    *,
    keywords: list[str],
    target_position: str = "FirstPage",
    match_types: list[str] | None = None,
    currency_code: str | None = None,
    language: str | None = None,
    location_ids: list[str] | None = None,
) -> list[KeywordBidEstimate]:
    """Estimate the bid needed to reach ``target_position`` for each keyword (FirstPage by default).

    Returns one ``BidEstimate`` per requested match type per keyword; ``estimated_min_bid`` is the
    headline "estimated first page bid" value.
    """
    if not keywords:
        raise ValueError("provide at least one keyword")
    if target_position not in TARGET_POSITIONS:
        raise ValueError(f"target_position must be one of {', '.join(TARGET_POSITIONS)}")
    mts = _validate_match_types(match_types) if match_types else ["Exact"]
    request = GetEstimatedBidByKeywordsRequest(
        keywords=[KeywordAndMatchType(keyword_text=k, match_types=list(mts)) for k in keywords],
        target_position_for_ads=target_position,
        currency_code=currency_code,
        language=language,
        location_ids=location_ids,
    )
    resp = client.call(AD_INSIGHT, "get_estimated_bid_by_keywords", request)
    items = as_list(first_attr(resp, "KeywordEstimatedBids", "keyword_estimated_bids"))
    return [KeywordBidEstimate.from_sdk(k) for k in items if k is not None]


def get_keyword_ideas(
    client: MsAdsClient,
    *,
    keywords: list[str] | None = None,
    url: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    location_ids: list[str] | None = None,
    network: str = DEFAULT_NETWORK,
    expand_ideas: bool = True,
    max_results: int = 100,
) -> list[KeywordIdeaSummary]:
    """Discover keyword ideas from seed queries and/or a landing-page URL (Keyword Planner).

    At least one of ``keywords`` (seed phrases) or ``url`` is required. ``location_ids`` defaults
    to the United States; ``language`` must name exactly one language.
    """
    if not keywords and not url:
        raise ValueError("provide keywords (seed phrases) and/or a url")
    if not expand_ideas and not keywords:
        raise ValueError("keywords are required when expand_ideas is false")
    request = GetKeywordIdeasRequest(
        expand_ideas=expand_ideas,
        idea_attributes=list(_IDEA_ATTRIBUTES),
        search_parameters=_idea_search_parameters(
            keywords=keywords,
            url=url,
            language=language,
            location_ids=location_ids,
            network=network,
        ),
    )
    resp = client.call(AD_INSIGHT, "get_keyword_ideas", request)
    items = as_list(first_attr(resp, "KeywordIdeas", "keyword_ideas"))
    out = [KeywordIdeaSummary.from_sdk(k) for k in items if k is not None]
    return out[:max_results] if max_results else out


def get_keyword_traffic_estimates(
    client: MsAdsClient,
    *,
    keywords: list[str],
    max_cpc: float,
    match_type: str = "Exact",
    language: str = DEFAULT_LANGUAGE,
    location_ids: list[str] | None = None,
    network: str = DEFAULT_NETWORK,
) -> list[KeywordTrafficEstimate]:
    """Estimate weekly clicks/impressions/cost for keywords at a given ``max_cpc`` bid.

    All keywords are estimated under one synthetic ad group at the supplied bid and match type.
    GetKeywordTrafficEstimates *requires* a location, language, and network criterion on the
    campaign estimator -- omitting them returns a 400 -- so they default to US / English / all
    search networks here, like ``get_keyword_ideas``.
    """
    if not keywords:
        raise ValueError("provide at least one keyword")
    mt = _validate_match_types([match_type])[0]
    keyword_estimators = [
        KeywordEstimator(keyword=Keyword(text=k, match_type=mt), max_cpc=max_cpc) for k in keywords
    ]
    locations = location_ids or [UNITED_STATES_LOCATION_ID]
    # Location, language, and network criteria are required by GetKeywordTrafficEstimates.
    criteria: list[Any] = [
        LanguageCriterion(language=language),
        NetworkCriterion(network=network),
        *[LocationCriterion(location_id=str(loc)) for loc in locations],
    ]
    request = GetKeywordTrafficEstimatesRequest(
        campaign_estimators=[
            CampaignEstimator(
                criteria=criteria,
                ad_group_estimators=[
                    AdGroupEstimator(max_cpc=max_cpc, keyword_estimators=keyword_estimators)
                ],
            )
        ]
    )
    resp = client.call(AD_INSIGHT, "get_keyword_traffic_estimates", request)
    out: list[KeywordTrafficEstimate] = []
    for ce in as_list(first_attr(resp, "CampaignEstimates", "campaign_estimates")):
        if ce is None:
            continue
        for age in as_list(first_attr(ce, "AdGroupEstimates", "ad_group_estimates")):
            if age is None:
                continue
            for ke in as_list(first_attr(age, "KeywordEstimates", "keyword_estimates")):
                if ke is None:
                    continue
                est = KeywordTrafficEstimate.from_sdk(ke)
                if est.max_cpc is None:
                    est.max_cpc = max_cpc
                out.append(est)
    return out


def check_first_page_bids(
    client: MsAdsClient,
    *,
    ad_group_id: str,
    campaign_id: str,
    target_position: str = "FirstPage",
    language: str | None = None,
    location_ids: list[str] | None = None,
) -> FirstPageBidReport:
    """Flag the ad group's keywords whose effective bid is below the estimated first-page bid.

    Reads the ad group's keywords and default bid, prices each keyword at its own match type via
    GetEstimatedBidByKeywords, then compares the effective bid (the keyword's own bid, or the
    ad-group default when it has none) against the first-page estimate. ``campaign_id`` is required
    to read the ad group's default bid -- keywords that inherit it can't be judged without it.
    """
    if target_position not in TARGET_POSITIONS:
        raise ValueError(f"target_position must be one of {', '.join(TARGET_POSITIONS)}")
    keywords = [k for k in campaigns.get_keywords(client, ad_group_id) if k.status != "Deleted"]
    default_bid = _ad_group_default_bid(client, campaign_id, ad_group_id)
    estimates = _estimate_for_keywords(
        client,
        keywords,
        target_position=target_position,
        language=language,
        location_ids=location_ids,
    )
    checks = _first_page_checks(keywords, default_bid=default_bid, estimates=estimates)
    currency = next((c.currency_code for c in checks if c.currency_code), None)
    return FirstPageBidReport(
        ad_group_id=str(ad_group_id),
        target_position=target_position,
        ad_group_default_bid=default_bid,
        currency_code=currency,
        keywords_checked=len(checks),
        below_first_page_count=sum(1 for c in checks if c.below_first_page_bid),
        undetermined_count=sum(1 for c in checks if c.below_first_page_bid is None),
        keywords=checks,
    )


def _estimate_for_keywords(
    client: MsAdsClient,
    keywords: list[KeywordSummary],
    *,
    target_position: str,
    language: str | None,
    location_ids: list[str] | None,
) -> list[KeywordBidEstimate]:
    """Price the ad group's distinct keyword texts at the match types present among them."""
    texts = sorted({k.text for k in keywords if k.text})
    if not texts:
        return []
    match_types = sorted({k.match_type for k in keywords if k.match_type in MATCH_TYPES})
    return estimate_keyword_bids(
        client,
        keywords=texts,
        target_position=target_position,
        match_types=match_types or None,
        language=language,
        location_ids=location_ids,
    )


def _ad_group_default_bid(client: MsAdsClient, campaign_id: str, ad_group_id: str) -> float | None:
    """The ad group's default CPC bid -- inherited by keywords that set no bid of their own."""
    target = str(ad_group_id)
    for ag in campaigns.get_ad_groups(client, campaign_id):
        if ag.id == target:
            return ag.cpc_bid
    return None


def _first_page_checks(
    keywords: list[KeywordSummary],
    *,
    default_bid: float | None,
    estimates: list[KeywordBidEstimate],
) -> list[FirstPageBidCheck]:
    """Join each keyword to its first-page estimate and flag the under-bid ones (sorted)."""
    lookup = _first_page_lookup(estimates)
    checks = [_build_check(k, default_bid, lookup) for k in keywords]
    checks.sort(key=_check_sort_key)
    return checks


def _first_page_lookup(
    estimates: list[KeywordBidEstimate],
) -> dict[tuple[str, str], BidEstimate]:
    """Index estimates by (keyword casefold, match type) for the per-keyword join."""
    out: dict[tuple[str, str], BidEstimate] = {}
    for ke in estimates:
        if not ke.keyword:
            continue
        for est in ke.estimates:
            if est.match_type:
                out[(ke.keyword.casefold(), est.match_type)] = est
    return out


def _build_check(
    kw: KeywordSummary,
    default_bid: float | None,
    lookup: dict[tuple[str, str], BidEstimate],
) -> FirstPageBidCheck:
    """Build one keyword's bid-vs-estimate verdict."""
    current, source = _effective_bid(kw.bid, default_bid)
    est = lookup.get((kw.text.casefold(), kw.match_type)) if kw.text and kw.match_type else None
    first_page = est.estimated_min_bid if est else None
    below: bool | None = None
    shortfall: float | None = None
    if current is not None and first_page is not None:
        below = current < first_page
        shortfall = round(first_page - current, 4) if below else None
    return FirstPageBidCheck(
        keyword_id=kw.id,
        keyword=kw.text,
        match_type=kw.match_type,
        status=kw.status,
        editorial_status=kw.editorial_status,
        current_bid=current,
        bid_source=source,
        estimated_first_page_bid=first_page,
        below_first_page_bid=below,
        shortfall=shortfall,
        currency_code=est.currency_code if est else None,
    )


def _effective_bid(
    keyword_bid: float | None, default_bid: float | None
) -> tuple[float | None, str | None]:
    """The bid that actually applies: the keyword's own, else the ad-group default."""
    if keyword_bid is not None:
        return keyword_bid, "keyword"
    if default_bid is not None:
        return default_bid, "ad_group"
    return None, None


def _check_sort_key(c: FirstPageBidCheck) -> tuple[int, float]:
    """Below-first-page first (largest shortfall first), then adequately bid, then undetermined."""
    if c.below_first_page_bid:
        return (0, -(c.shortfall or 0.0))
    if c.below_first_page_bid is None:
        return (2, 0.0)
    return (1, 0.0)


def _idea_search_parameters(
    *,
    keywords: list[str] | None,
    url: str | None,
    language: str,
    location_ids: list[str] | None,
    network: str,
) -> list[Any]:
    """Build the (required) language/location/network params plus any query/url seed params.

    GetKeywordIdeas requires a LanguageSearchParameter, a LocationSearchParameter, and a
    NetworkSearchParameter; the seed comes from a QuerySearchParameter and/or UrlSearchParameter.
    """
    locations = location_ids or [UNITED_STATES_LOCATION_ID]
    params: list[Any] = [
        LanguageSearchParameter(languages=[LanguageCriterion(language=language)]),
        LocationSearchParameter(
            locations=[LocationCriterion(location_id=str(loc)) for loc in locations]
        ),
        NetworkSearchParameter(network=NetworkCriterion(network=network)),
    ]
    if keywords:
        params.append(QuerySearchParameter(queries=list(keywords)))
    if url:
        params.append(UrlSearchParameter(url=url))
    return params


def _validate_match_types(values: list[str]) -> list[str]:
    """Reject unknown match types early with a clear message (the SDK enum error is opaque)."""
    bad = [v for v in values if v not in MATCH_TYPES]
    if bad:
        raise ValueError(f"invalid match type(s) {bad}; use one of {', '.join(MATCH_TYPES)}")
    return values
