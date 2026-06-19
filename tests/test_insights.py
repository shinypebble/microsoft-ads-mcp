"""Ad Insight (keyword research) flows: request shaping and response parsing, offline.

Mirrors the other service tests: a scripted client records the (service, method, request) tuples
and hands back canned SDK response models built via ``from_dict``.
"""

from __future__ import annotations

from typing import Any

import pytest
from openapi_client.models.adinsight.get_estimated_bid_by_keywords_response import (
    GetEstimatedBidByKeywordsResponse,
)
from openapi_client.models.adinsight.get_keyword_ideas_response import GetKeywordIdeasResponse
from openapi_client.models.adinsight.get_keyword_traffic_estimates_response import (
    GetKeywordTrafficEstimatesResponse,
)
from openapi_client.models.campaign.get_ad_groups_by_campaign_id_response import (
    GetAdGroupsByCampaignIdResponse,
)
from openapi_client.models.campaign.get_keywords_by_ad_group_id_response import (
    GetKeywordsByAdGroupIdResponse,
)

from microsoft_ads_mcp.domain.entities import BidEstimate, KeywordBidEstimate, KeywordSummary
from microsoft_ads_mcp.services import insights


class _ScriptedClient:
    account_id = "123"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        return self._responses.pop(0)


def _param(params: list[Any], name: str) -> Any:
    return next(p for p in params if type(p).__name__ == name)


# --------------------------------------------------------------------- estimate_keyword_bids


def test_estimate_keyword_bids_request_shape_and_parse() -> None:
    resp = GetEstimatedBidByKeywordsResponse.from_dict(
        {
            "KeywordEstimatedBids": [
                {
                    "Keyword": "running shoes",
                    "EstimatedBids": [
                        {
                            "MatchType": "Exact",
                            "EstimatedMinBid": 1.23,
                            "AverageCPC": 0.98,
                            "CTR": 2.5,
                            "MinImpressionsPerWeek": "100",
                            "MaxImpressionsPerWeek": "250",
                            "MinClicksPerWeek": 3.0,
                            "MaxClicksPerWeek": 7.0,
                        }
                    ],
                }
            ]
        }
    )
    client = _ScriptedClient([resp])

    out = insights.estimate_keyword_bids(
        client, keywords=["running shoes"], target_position="FirstPage"
    )

    service, method, request = client.calls[0]
    assert (service, method) == ("AdInsightService", "get_estimated_bid_by_keywords")
    assert request.target_position_for_ads == "FirstPage"
    assert [kw.keyword_text for kw in request.keywords] == ["running shoes"]
    assert request.keywords[0].match_types == ["Exact"]  # default match type

    assert len(out) == 1
    est = out[0]
    assert est.keyword == "running shoes"
    assert est.estimates[0].estimated_min_bid == 1.23
    assert est.estimates[0].match_type == "Exact"
    assert est.estimates[0].min_impressions_per_week == 100  # string coerced to int
    assert est.estimates[0].max_impressions_per_week == 250


def test_estimate_keyword_bids_passes_explicit_match_types() -> None:
    resp = GetEstimatedBidByKeywordsResponse.from_dict({"KeywordEstimatedBids": []})
    client = _ScriptedClient([resp])
    insights.estimate_keyword_bids(client, keywords=["a", "b"], match_types=["Broad", "Phrase"])
    request = client.calls[0][2]
    assert request.keywords[0].match_types == ["Broad", "Phrase"]
    assert [kw.keyword_text for kw in request.keywords] == ["a", "b"]


def test_estimate_keyword_bids_rejects_empty_and_bad_position() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="at least one keyword"):
        insights.estimate_keyword_bids(client, keywords=[])
    with pytest.raises(ValueError, match="target_position"):
        insights.estimate_keyword_bids(client, keywords=["x"], target_position="Top")


def test_estimate_keyword_bids_surfaces_average_cpc_verbatim() -> None:
    # Microsoft derives AverageCPC = max_total_cost / max_clicks, so for a competitive keyword it
    # can exceed the first-page EstimatedMinBid. We must surface it verbatim, never rescale/cap it.
    resp = GetEstimatedBidByKeywordsResponse.from_dict(
        {
            "KeywordEstimatedBids": [
                {
                    "Keyword": "internet providers",
                    "EstimatedBids": [
                        {
                            "MatchType": "Exact",
                            "EstimatedMinBid": 5.68,
                            "AverageCPC": 23.49,
                            "MaxClicksPerWeek": 10.0,
                            "MaxTotalCostPerWeek": 234.9,
                        }
                    ],
                }
            ]
        }
    )
    client = _ScriptedClient([resp])
    e = insights.estimate_keyword_bids(client, keywords=["internet providers"])[0].estimates[0]
    assert e.estimated_min_bid == 5.68
    assert e.average_cpc == 23.49  # surfaced as-is, not capped to the bid
    # ...and consistent with Microsoft's formula (max_total_cost / max_clicks).
    assert e.average_cpc == pytest.approx(e.max_total_cost_per_week / e.max_clicks_per_week)


# --------------------------------------------------------------------------- get_keyword_ideas


def test_keyword_ideas_builds_required_params_and_defaults_us() -> None:
    resp = GetKeywordIdeasResponse.from_dict(
        {
            "KeywordIdeas": [
                {
                    "Keyword": "trail running shoes",
                    "Source": "SuggestionFromKeyword",
                    "MonthlySearchCounts": ["1000", "1200", "800"],
                    "SuggestedBid": 1.75,
                    "Competition": "Medium",
                }
            ]
        }
    )
    client = _ScriptedClient([resp])

    out = insights.get_keyword_ideas(client, keywords=["running shoes"])

    service, method, request = client.calls[0]
    assert (service, method) == ("AdInsightService", "get_keyword_ideas")
    params = request.search_parameters
    # Language / Location / Network are always present; Query is added from the seed keywords.
    assert _param(params, "LanguageSearchParameter").languages[0].language == "English"
    assert [c.location_id for c in _param(params, "LocationSearchParameter").locations] == ["190"]
    assert _param(params, "NetworkSearchParameter").network.network == (
        "OwnedAndOperatedAndSyndicatedSearch"
    )
    assert _param(params, "QuerySearchParameter").queries == ["running shoes"]
    assert "MonthlySearchCounts" in request.idea_attributes

    idea = out[0]
    assert idea.keyword == "trail running shoes"
    assert idea.source == "SuggestionFromKeyword"
    assert idea.monthly_search_counts == [1000, 1200, 800]
    assert idea.avg_monthly_searches == 1000  # round(3000/3)
    assert idea.suggested_bid == 1.75
    assert idea.competition == "Medium"


def test_keyword_ideas_uses_url_seed_and_custom_location() -> None:
    resp = GetKeywordIdeasResponse.from_dict({"KeywordIdeas": []})
    client = _ScriptedClient([resp])
    insights.get_keyword_ideas(client, url="contoso.com/shoes", location_ids=["191", "192"])
    params = client.calls[0][2].search_parameters
    assert _param(params, "UrlSearchParameter").url == "contoso.com/shoes"
    assert [c.location_id for c in _param(params, "LocationSearchParameter").locations] == [
        "191",
        "192",
    ]
    assert not any(type(p).__name__ == "QuerySearchParameter" for p in params)


def test_keyword_ideas_requires_a_seed() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match=r"keywords .* and/or a url"):
        insights.get_keyword_ideas(client)


def test_keyword_ideas_no_expand_requires_keywords() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="expand_ideas is false"):
        insights.get_keyword_ideas(client, url="contoso.com", expand_ideas=False)


# ----------------------------------------------------------------- get_keyword_traffic_estimates


def test_traffic_estimates_request_shape_and_parse() -> None:
    resp = GetKeywordTrafficEstimatesResponse.from_dict(
        {
            "CampaignEstimates": [
                {
                    "AdGroupEstimates": [
                        {
                            "KeywordEstimates": [
                                {
                                    "Keyword": {"Text": "running shoes", "MatchType": "Exact"},
                                    "Minimum": {
                                        "Clicks": 10.0,
                                        "Impressions": 100.0,
                                        "TotalCost": 5.0,
                                        "AveragePosition": 3.0,
                                    },
                                    "Maximum": {
                                        "Clicks": 20.0,
                                        "Impressions": 220.0,
                                        "TotalCost": 12.0,
                                        "AveragePosition": 1.5,
                                    },
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    )
    client = _ScriptedClient([resp])

    out = insights.get_keyword_traffic_estimates(client, keywords=["running shoes"], max_cpc=2.5)

    service, method, request = client.calls[0]
    assert (service, method) == ("AdInsightService", "get_keyword_traffic_estimates")
    campaign = request.campaign_estimators[0]
    # Location / language / network criteria are required, else the API returns 400 Bad Request.
    ctypes = {type(c).__name__ for c in campaign.criteria}
    assert {"LanguageCriterion", "NetworkCriterion", "LocationCriterion"} <= ctypes
    loc = next(c for c in campaign.criteria if type(c).__name__ == "LocationCriterion")
    assert loc.location_id == "190"  # United States default
    ag = campaign.ad_group_estimators[0]
    assert ag.max_cpc == 2.5
    assert ag.keyword_estimators[0].keyword.text == "running shoes"
    assert ag.keyword_estimators[0].keyword.match_type == "Exact"
    assert ag.keyword_estimators[0].max_cpc == 2.5

    est = out[0]
    assert est.keyword == "running shoes" and est.match_type == "Exact"
    assert (est.min_clicks, est.max_clicks) == (10.0, 20.0)
    assert (est.min_impressions, est.max_impressions) == (100.0, 220.0)
    assert (est.min_avg_position, est.max_avg_position) == (3.0, 1.5)
    assert est.max_cpc == 2.5  # echoed from the request bid


def test_traffic_estimates_custom_location_and_network() -> None:
    resp = GetKeywordTrafficEstimatesResponse.from_dict({"CampaignEstimates": []})
    client = _ScriptedClient([resp])
    insights.get_keyword_traffic_estimates(
        client, keywords=["x"], max_cpc=1.0, location_ids=["191"], network="OwnedAndOperatedOnly"
    )
    criteria = client.calls[0][2].campaign_estimators[0].criteria
    loc = next(c for c in criteria if type(c).__name__ == "LocationCriterion")
    net = next(c for c in criteria if type(c).__name__ == "NetworkCriterion")
    assert loc.location_id == "191"
    assert net.network == "OwnedAndOperatedOnly"


def test_traffic_estimates_rejects_empty_and_bad_match_type() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="at least one keyword"):
        insights.get_keyword_traffic_estimates(client, keywords=[], max_cpc=1.0)
    with pytest.raises(ValueError, match="invalid match type"):
        insights.get_keyword_traffic_estimates(
            client, keywords=["x"], max_cpc=1.0, match_type="Aggregate"
        )


# ------------------------------------------------------------------------------- pure helpers


def test_validate_match_types() -> None:
    assert insights._validate_match_types(["Broad", "Exact"]) == ["Broad", "Exact"]
    with pytest.raises(ValueError, match="invalid match type"):
        insights._validate_match_types(["Exact", "Nope"])


def test_idea_search_parameters_minimal_set() -> None:
    params = insights._idea_search_parameters(
        keywords=None,
        url="x.com",
        language="French",
        location_ids=None,
        network="OwnedAndOperatedOnly",
    )
    names = {type(p).__name__ for p in params}
    assert {"LanguageSearchParameter", "LocationSearchParameter", "NetworkSearchParameter"} <= names
    assert "QuerySearchParameter" not in names
    assert _param(params, "LanguageSearchParameter").languages[0].language == "French"


# ------------------------------------------------------------------------ check_first_page_bids


def _bid_estimate(keyword: str, match_type: str, min_bid: float, currency: str = "USD") -> Any:
    return KeywordBidEstimate(
        keyword=keyword,
        estimates=[
            BidEstimate(match_type=match_type, estimated_min_bid=min_bid, currency_code=currency)
        ],
    )


def test_first_page_checks_flags_and_sorts_under_bid_keywords() -> None:
    keywords = [
        KeywordSummary(id="1", text="running shoes", match_type="Exact", status="Active", bid=0.30),
        KeywordSummary(id="2", text="trail shoes", match_type="Exact", status="Active", bid=0.90),
    ]
    estimates = [
        _bid_estimate("running shoes", "Exact", 0.50),
        _bid_estimate("trail shoes", "Exact", 0.45),
    ]
    checks = insights._first_page_checks(keywords, default_bid=None, estimates=estimates)

    # running shoes is below (0.30 < 0.50) and sorts first; trail shoes is adequately bid.
    assert [c.keyword for c in checks] == ["running shoes", "trail shoes"]
    low = checks[0]
    assert low.below_first_page_bid is True
    assert (low.current_bid, low.bid_source) == (0.30, "keyword")
    assert low.estimated_first_page_bid == 0.50
    assert low.shortfall == pytest.approx(0.20)
    assert low.currency_code == "USD"
    assert checks[1].below_first_page_bid is False
    assert checks[1].shortfall is None


def test_first_page_checks_inherits_ad_group_default_bid() -> None:
    # No keyword bid -> the effective bid is the ad-group default (0.25), below the 0.40 estimate.
    keywords = [
        KeywordSummary(id="1", text="hiking boots", match_type="Phrase", status="Active", bid=None)
    ]
    checks = insights._first_page_checks(
        keywords, default_bid=0.25, estimates=[_bid_estimate("hiking boots", "Phrase", 0.40)]
    )
    c = checks[0]
    assert (c.current_bid, c.bid_source) == (0.25, "ad_group")
    assert c.below_first_page_bid is True
    assert c.shortfall == pytest.approx(0.15)


def test_first_page_checks_undetermined_without_estimate_or_bid() -> None:
    # "no estimate" has a bid but Microsoft returned no estimate; "no bid" has an estimate but no
    # bid and no ad-group default -- both are undetermined ("unknown"), not "adequately bid".
    keywords = [
        KeywordSummary(id="1", text="no estimate", match_type="Exact", status="Active", bid=0.50),
        KeywordSummary(id="2", text="no bid", match_type="Exact", status="Active", bid=None),
    ]
    checks = insights._first_page_checks(
        keywords, default_bid=None, estimates=[_bid_estimate("no bid", "Exact", 0.30)]
    )
    by_kw = {c.keyword: c for c in checks}
    assert by_kw["no estimate"].below_first_page_bid is None
    assert by_kw["no estimate"].estimated_first_page_bid is None
    assert by_kw["no bid"].below_first_page_bid is None
    assert (by_kw["no bid"].current_bid, by_kw["no bid"].bid_source) == (None, None)


def test_first_page_checks_joins_on_match_type() -> None:
    # Only an Exact estimate exists for "shoes"; the Broad keyword has no matching estimate.
    keywords = [KeywordSummary(id="1", text="shoes", match_type="Broad", status="Active", bid=0.10)]
    checks = insights._first_page_checks(
        keywords, default_bid=None, estimates=[_bid_estimate("shoes", "Exact", 0.99)]
    )
    assert checks[0].below_first_page_bid is None
    assert checks[0].estimated_first_page_bid is None


def test_check_first_page_bids_orchestration() -> None:
    keywords_resp = GetKeywordsByAdGroupIdResponse.from_dict(
        {
            "Keywords": [
                {
                    "Id": "11",
                    "Text": "running shoes",
                    "MatchType": "Exact",
                    "Status": "Active",
                    "EditorialStatus": "Active",
                    "Bid": {"Amount": 0.30},
                },
                {  # no Bid -> inherits the ad-group default
                    "Id": "12",
                    "Text": "hiking boots",
                    "MatchType": "Exact",
                    "Status": "Active",
                    "EditorialStatus": "Active",
                },
                {  # no estimate returned for it -> undetermined
                    "Id": "13",
                    "Text": "trail shoes",
                    "MatchType": "Exact",
                    "Status": "Active",
                    "Bid": {"Amount": 0.20},
                },
                {  # Deleted -> excluded from the check entirely
                    "Id": "14",
                    "Text": "old kw",
                    "MatchType": "Exact",
                    "Status": "Deleted",
                    "Bid": {"Amount": 0.01},
                },
            ]
        }
    )
    adgroups_resp = GetAdGroupsByCampaignIdResponse.from_dict(
        {"AdGroups": [{"Id": "99", "Name": "AG", "Status": "Active", "CpcBid": {"Amount": 0.60}}]}
    )
    bids_resp = GetEstimatedBidByKeywordsResponse.from_dict(
        {
            "KeywordEstimatedBids": [
                {
                    "Keyword": "running shoes",
                    "EstimatedBids": [
                        {"MatchType": "Exact", "EstimatedMinBid": 0.50, "CurrencyCode": "USD"}
                    ],
                },
                {
                    "Keyword": "hiking boots",
                    "EstimatedBids": [
                        {"MatchType": "Exact", "EstimatedMinBid": 0.45, "CurrencyCode": "USD"}
                    ],
                },
                # trail shoes intentionally absent -> undetermined
            ]
        }
    )
    client = _ScriptedClient([keywords_resp, adgroups_resp, bids_resp])

    report = insights.check_first_page_bids(client, ad_group_id="99", campaign_id="7")

    # Fetch order: keywords, then the ad group (for its default bid), then the bid estimates.
    assert [m for (_s, m, _r) in client.calls] == [
        "get_keywords_by_ad_group_id",
        "get_ad_groups_by_campaign_id",
        "get_estimated_bid_by_keywords",
    ]
    # The estimate prices the distinct, non-deleted keyword texts at the Exact match type present.
    bid_req = client.calls[2][2]
    assert sorted(k.keyword_text for k in bid_req.keywords) == [
        "hiking boots",
        "running shoes",
        "trail shoes",
    ]
    assert bid_req.keywords[0].match_types == ["Exact"]

    assert report.ad_group_id == "99"
    assert report.ad_group_default_bid == 0.60
    assert report.currency_code == "USD"
    assert report.keywords_checked == 3  # the Deleted keyword is excluded
    assert report.below_first_page_count == 1  # running shoes (0.30 < 0.50)
    assert report.undetermined_count == 1  # trail shoes (no estimate)

    # running shoes is flagged and sorts first; hiking boots inherits 0.60 >= 0.45 (adequate).
    first = report.keywords[0]
    assert first.keyword == "running shoes"
    assert first.below_first_page_bid is True
    assert first.bid_source == "keyword"
    hiking = next(c for c in report.keywords if c.keyword == "hiking boots")
    assert (hiking.bid_source, hiking.current_bid) == ("ad_group", 0.60)
    assert hiking.below_first_page_bid is False


def test_check_first_page_bids_rejects_bad_position() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="target_position"):
        insights.check_first_page_bids(
            client, ad_group_id="1", campaign_id="2", target_position="X"
        )
