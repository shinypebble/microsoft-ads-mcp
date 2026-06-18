"""Mutation flows build the right partial requests offline (no network).

The highest-risk behavior is partial update: send only id + changed fields (so the endpoint
does not reject round-tripped read-only fields), keep polymorphic ``Type`` discriminators, and
re-send ``final_urls`` as a list. We assert on the request objects the service hands the client.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from microsoft_ads_mcp.domain.entities import AdSummary
from microsoft_ads_mcp.services import mutations


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


def test_update_campaign_sends_only_changed_fields() -> None:
    client = _FakeClient()
    result = mutations.update_campaign(client, campaign_id="1", name="GCF_Search_Core_US")
    assert result.ok and result.ids == ["1"]
    _, method, request = client.calls[0]
    assert method == "update_campaigns"
    assert request.campaigns[0].to_dict() == {"Id": "1", "Name": "GCF_Search_Core_US"}


def test_update_rsa_repoints_url_as_list_with_discriminator() -> None:
    client = _FakeClient()
    result = mutations.update_responsive_search_ad(
        client, ad_group_id="7", ad_id="9", final_url="https://getconnectedfast.com/save/"
    )
    assert result.ok and result.ids == ["9"]
    _, method, request = client.calls[0]
    assert method == "update_ads"
    assert request.ad_group_id == "7"
    ad = request.ads[0]
    assert ad.id == "9"
    assert ad.type.value == "ResponsiveSearch"  # discriminator required for polymorphic dispatch
    assert ad.final_urls == ["https://getconnectedfast.com/save/"]
    assert ad.headlines is None and ad.descriptions is None  # untouched fields stay unset


def test_update_keyword_wraps_bid() -> None:
    client = _FakeClient()
    mutations.update_keyword(client, ad_group_id="7", keyword_id="42", bid=2.5)
    _, method, request = client.calls[0]
    assert method == "update_keywords"
    kw = request.keywords[0]
    assert kw.id == "42"
    assert kw.bid.amount == 2.5


def test_delete_campaigns_echoes_ids_and_reports_count() -> None:
    client = _FakeClient()
    result = mutations.delete_campaigns(client, campaign_ids=["100", "200"])
    assert result.ok and result.ids == ["100", "200"]
    assert "2 campaigns" in result.message
    _, method, request = client.calls[0]
    assert method == "delete_campaigns"
    assert request.account_id == "123" and request.campaign_ids == ["100", "200"]


def test_invalid_status_is_rejected() -> None:
    client = _FakeClient()
    try:
        mutations.update_campaign(client, campaign_id="1", status="Archived")
    except ValueError as exc:
        assert "Active" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected ValueError for an invalid status")


def test_ad_summary_surfaces_rsa_copy() -> None:
    """AdSummary.from_sdk unwraps headline/description text and display paths (issue 10)."""
    ad = SimpleNamespace(
        id=9,
        type="ResponsiveSearch",
        status="Active",
        final_urls=["https://getconnectedfast.com/save/"],
        headlines=[
            SimpleNamespace(asset=SimpleNamespace(text="Fast Internet")),
            SimpleNamespace(asset=SimpleNamespace(text="Switch & Save")),
        ],
        descriptions=[SimpleNamespace(asset=SimpleNamespace(text="Compare plans now"))],
        path1="save",
        path2=None,
    )
    summary = AdSummary.from_sdk(ad)
    assert summary.headlines == ["Fast Internet", "Switch & Save"]
    assert summary.descriptions == ["Compare plans now"]
    assert summary.path1 == "save"
    assert summary.final_url == "https://getconnectedfast.com/save/"
