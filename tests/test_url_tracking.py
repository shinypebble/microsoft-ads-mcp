"""URL tracking across the tree and at the account level (offline; no network).

Two shapes are exercised: that reads *parse* tracking template / Final URL suffix / custom
parameters out of SDK objects, and that writes *build* the right request bodies (including the
nested ``UrlCustomParameters`` and the account-level ``AccountProperties`` name/value rows).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from microsoft_ads_mcp.domain.entities import (
    AccountUrlOptions,
    CampaignSummary,
    KeywordSummary,
)
from microsoft_ads_mcp.services import account_properties, mutations


class _Resp:
    """A response with no partial errors (success)."""

    partial_errors = None


class _FakeClient:
    account_id = "123"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> _Resp:
        self.calls.append((service, method, request))
        return _Resp()


def _custom_params_obj(**pairs: str) -> SimpleNamespace:
    """Mimic an SDK ``UrlCustomParameters`` (Parameters -> list of Key/Value)."""
    params = [SimpleNamespace(key=k, value=v) for k, v in pairs.items()]
    return SimpleNamespace(parameters=params)


# --------------------------------------------------------------------- hierarchy reads


def test_campaign_summary_surfaces_url_tracking() -> None:
    c = SimpleNamespace(
        id=487928625,
        name="GCF_Search_Core_US",
        status="Active",
        campaign_type="Search",
        daily_budget=50.0,
        tracking_url_template="{lpurl}?utm_source=bing",
        final_url_suffix="cid={msclkid}",
        url_custom_parameters=_custom_params_obj(season="summer", region="us"),
    )
    summary = CampaignSummary.from_sdk(c)
    assert summary.tracking_url_template == "{lpurl}?utm_source=bing"
    assert summary.final_url_suffix == "cid={msclkid}"
    assert summary.url_custom_parameters == {"season": "summer", "region": "us"}


def test_keyword_summary_surfaces_final_url_and_blank_tracking() -> None:
    # A keyword that inherits everything: Final URL set, no keyword-level overrides.
    kw = SimpleNamespace(
        id=76554248594440,
        text="fast internet",
        match_type="Phrase",
        status="Active",
        final_urls=["https://getconnectedfast.com/"],
        tracking_url_template=None,
        url_custom_parameters=None,
    )
    summary = KeywordSummary.from_sdk(kw)
    assert summary.final_url == "https://getconnectedfast.com/"
    assert summary.tracking_url_template is None
    assert summary.url_custom_parameters is None  # absent stays absent, not {}


# --------------------------------------------------------------------- hierarchy writes


def test_update_campaign_builds_custom_parameters() -> None:
    client = _FakeClient()
    result = mutations.update_campaign(
        client, campaign_id="1", url_custom_parameters={"src": "bing"}
    )
    assert result.ok
    _, method, request = client.calls[0]
    assert method == "update_campaigns"
    assert request.campaigns[0].to_dict() == {
        "Id": "1",
        "UrlCustomParameters": {"Parameters": [{"Key": "src", "Value": "bing"}]},
    }


def test_update_keyword_sets_tracking_template_and_custom_params() -> None:
    client = _FakeClient()
    mutations.update_keyword(
        client,
        ad_group_id="7",
        keyword_id="42",
        tracking_url_template="{lpurl}?kw={keyword}",
        url_custom_parameters={"tier": "gold"},
    )
    _, method, request = client.calls[0]
    assert method == "update_keywords"
    got = request.keywords[0].to_dict()
    assert got["TrackingUrlTemplate"] == "{lpurl}?kw={keyword}"
    assert got["UrlCustomParameters"] == {"Parameters": [{"Key": "tier", "Value": "gold"}]}


def test_add_keywords_applies_tracking_template_to_every_keyword() -> None:
    client = _FakeClient()
    mutations.add_keywords(
        client,
        ad_group_id="7",
        keywords=["alpha", "beta"],
        tracking_url_template="{lpurl}?src=bing",
    )
    _, _, request = client.calls[0]
    assert [kw.text for kw in request.keywords] == ["alpha", "beta"]
    assert all(kw.tracking_url_template == "{lpurl}?src=bing" for kw in request.keywords)


def test_empty_custom_parameters_are_omitted_not_cleared() -> None:
    # None / empty dict must not emit an UrlCustomParameters field (partial update = unchanged).
    client = _FakeClient()
    mutations.update_campaign(client, campaign_id="1", name="X", url_custom_parameters=None)
    _, _, request = client.calls[0]
    assert "UrlCustomParameters" not in request.campaigns[0].to_dict()


# --------------------------------------------------------------------- account-level options


def test_account_url_options_parses_properties() -> None:
    # Mirrors the live account: template set, suffix blank, msclkid on, parallel tracking unset.
    opts = AccountUrlOptions.from_properties(
        {
            "TrackingUrlTemplate": "{lpurl}?utm_source=bing&utm_medium=cpc",
            "FinalUrlSuffix": "",
            "MSCLKIDAutoTaggingEnabled": "true",
            "AdClickParallelTracking": None,
        }
    )
    assert opts.tracking_url_template == "{lpurl}?utm_source=bing&utm_medium=cpc"
    assert opts.final_url_suffix is None  # blank -> None (treated as unset)
    assert opts.msclkid_auto_tagging_enabled is True
    assert opts.ad_click_parallel_tracking is None


def test_set_account_url_options_builds_named_value_rows() -> None:
    client = _FakeClient()
    result = account_properties.set_account_url_options(
        client,
        tracking_url_template="{lpurl}?utm_source=bing",
        msclkid_auto_tagging_enabled=True,
    )
    assert result.ok
    _, method, request = client.calls[0]
    assert method == "set_account_properties"
    rows = {
        (p.name.value if hasattr(p.name, "value") else str(p.name)): p.value
        for p in request.account_properties
    }
    assert rows == {
        "TrackingUrlTemplate": "{lpurl}?utm_source=bing",
        "MSCLKIDAutoTaggingEnabled": "true",  # bool rendered as Microsoft's lowercase string
    }


def test_set_account_url_options_noop_without_fields() -> None:
    client = _FakeClient()
    result = account_properties.set_account_url_options(client)
    assert not result.ok
    assert not client.calls  # nothing sent when no field is provided
