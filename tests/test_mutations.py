"""Mutation flows build the right partial requests offline (no network).

The highest-risk behavior is partial update: send only id + changed fields (so the endpoint
does not reject round-tripped read-only fields), keep polymorphic ``Type`` discriminators, and
re-send ``final_urls`` as a list. We assert on the request objects the service hands the client.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

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

    # create_*/add_* paths read the raw JSON via call_raw; first_attr is dict-or-object tolerant.
    def call_raw(self, service: str, method: str, request: Any) -> _Resp:
        return self.call(service, method, request)


class _ConstClient:
    """Returns one fixed response for every call (for inspecting partial-error handling)."""

    account_id = "123"

    def __init__(self, resp: Any) -> None:
        self._resp = resp
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        return self._resp

    def call_raw(self, service: str, method: str, request: Any) -> Any:
        return self.call(service, method, request)


def _batch_error(code: str, message: str = "") -> Any:
    return SimpleNamespace(error_code=code, message=message)


def test_update_campaign_sends_only_changed_fields() -> None:
    client = _FakeClient()
    result = mutations.update_campaign(client, campaign_id="1", name="GCF_Search_Core_US")
    assert result.ok and result.ids == ["1"]
    _, method, request = client.calls[0]
    assert method == "update_campaigns"
    assert request.campaigns[0].to_dict() == {"Id": "1", "Name": "GCF_Search_Core_US"}


def test_update_campaign_sets_inline_bid_strategy_max_clicks() -> None:
    # The motivating case: switch to Maximize Clicks with a Maximum CPC limit. The scheme carries
    # its own Type discriminator and the max_cpc is wrapped as a Bid(Amount).
    client = _FakeClient()
    result = mutations.update_campaign(
        client, campaign_id="1", bid_strategy_type="MaxClicks", max_cpc=2.5
    )
    assert result.ok and result.ids == ["1"]
    _, method, request = client.calls[0]
    assert method == "update_campaigns"
    assert request.campaigns[0].to_dict() == {
        "Id": "1",
        "BiddingScheme": {"Type": "MaxClicks", "MaxCpc": {"Amount": 2.5}},
    }


def test_update_campaign_inline_bid_strategy_without_params() -> None:
    client = _FakeClient()
    result = mutations.update_campaign(client, campaign_id="1", bid_strategy_type="EnhancedCpc")
    assert result.ok
    request = client.calls[0][2]
    assert request.campaigns[0].to_dict() == {"Id": "1", "BiddingScheme": {"Type": "EnhancedCpc"}}


def test_update_campaign_target_cpa_carries_target() -> None:
    client = _FakeClient()
    mutations.update_campaign(
        client, campaign_id="1", bid_strategy_type="TargetCpa", target_cpa=25.0
    )
    request = client.calls[0][2]
    assert request.campaigns[0].to_dict() == {
        "Id": "1",
        "BiddingScheme": {"Type": "TargetCpa", "TargetCpa": 25.0},
    }


def test_update_campaign_accepts_long_form_bid_strategy_type() -> None:
    # get_campaigns reports the long "TargetRoasBiddingScheme" discriminator for TargetRoas; the
    # write path normalizes it so a read value round-trips straight back.
    client = _FakeClient()
    mutations.update_campaign(
        client, campaign_id="1", bid_strategy_type="TargetRoasBiddingScheme", target_roas=4.0
    )
    request = client.calls[0][2]
    assert request.campaigns[0].to_dict() == {
        "Id": "1",
        "BiddingScheme": {"Type": "TargetRoasBiddingScheme", "TargetRoas": 4.0},
    }


def test_create_campaign_sets_inline_bid_strategy() -> None:
    client = _FakeClient()
    result = mutations.create_campaign(
        client, name="New", daily_budget=10.0, bid_strategy_type="MaxClicks", max_cpc=1.0
    )
    assert (
        result.ok is False
    )  # _FakeClient returns no ids, so ok is False -- we only check the request
    method, request = client.calls[0][1], client.calls[0][2]
    assert method == "add_campaigns"
    assert request.campaigns[0].bidding_scheme.to_dict() == {
        "Type": "MaxClicks",
        "MaxCpc": {"Amount": 1.0},
    }


def test_update_campaign_rejects_both_portfolio_and_inline_strategy() -> None:
    with pytest.raises(ValueError, match="not both"):
        mutations.update_campaign(
            _FakeClient(), campaign_id="1", bid_strategy_id="55", bid_strategy_type="MaxClicks"
        )


def test_bid_strategy_knob_requires_a_type() -> None:
    with pytest.raises(ValueError, match="bid_strategy_type is required"):
        mutations.update_campaign(_FakeClient(), campaign_id="1", max_cpc=2.0)


def test_bid_strategy_rejects_inapplicable_knob() -> None:
    with pytest.raises(ValueError, match="target_cpa is not valid"):
        mutations.update_campaign(
            _FakeClient(), campaign_id="1", bid_strategy_type="MaxClicks", target_cpa=25.0
        )


def test_bid_strategy_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="bid_strategy_type must be one of"):
        mutations.update_campaign(_FakeClient(), campaign_id="1", bid_strategy_type="Nonsense")


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


def test_delete_campaign_idempotent_when_already_deleted() -> None:
    # Re-deleting an already-Deleted campaign returns CampaignServiceInvalidCampaignStatus; we treat
    # that as a no-op success rather than leaking the raw error (issue 13).
    resp = SimpleNamespace(
        partial_errors=[
            _batch_error(
                "CampaignServiceInvalidCampaignStatus",
                "The campaign status is invalid for the current operation.",
            )
        ]
    )
    client = _ConstClient(resp)
    result = mutations.delete_campaigns(client, campaign_ids=["100"])
    assert result.ok and result.ids == ["100"]
    assert "already deleted" in result.message
    assert result.partial_errors == []  # the idempotent error is suppressed


def test_delete_campaign_still_reports_real_errors() -> None:
    # A real failure mixed with an already-deleted one still fails, surfacing only the real error.
    resp = SimpleNamespace(
        partial_errors=[
            _batch_error("CampaignServiceInvalidCampaignStatus", "already gone"),
            _batch_error("CampaignServiceEditorialError", "boom"),
        ]
    )
    client = _ConstClient(resp)
    result = mutations.delete_campaigns(client, campaign_ids=["100", "200"])
    assert not result.ok
    assert result.partial_errors == ["CampaignServiceEditorialError: boom"]


def test_delete_campaign_idempotent_when_not_found() -> None:
    # A ...DoesNotExist code (never existed) is also treated as a no-op.
    resp = SimpleNamespace(
        partial_errors=[_batch_error("CampaignServiceCampaignDoesNotExist", "no such campaign")]
    )
    result = mutations.delete_campaigns(_ConstClient(resp), campaign_ids=["999"])
    assert result.ok and result.partial_errors == []


def test_create_rsa_preserves_dki_function() -> None:
    # A {KeyWord:...} headline longer than 30 literal chars must NOT be sliced (that drops the
    # closing brace -> InvalidFunctionFormat); only the rendered keyword counts toward 30 (iss. 19).
    client = _ConstClient(SimpleNamespace(ad_ids=["9"]))
    result = mutations.create_responsive_search_ad(
        client,
        ad_group_id="7",
        final_url="https://getconnectedfast.com/move/",
        headlines=["{KeyWord:Internet When You Move}", "Plain headline"],
        descriptions=["A description"],
    )
    assert result.ok
    texts = [h.asset.text for h in client.calls[0][2].ads[0].headlines]
    assert texts[0] == "{KeyWord:Internet When You Move}"  # intact, brace preserved


def test_create_rsa_truncates_plain_headline() -> None:
    client = _ConstClient(SimpleNamespace(ad_ids=["9"]))
    mutations.create_responsive_search_ad(
        client,
        ad_group_id="7",
        final_url="https://x.test/",
        headlines=["A" * 40],
        descriptions=["d"],
    )
    assert client.calls[0][2].ads[0].headlines[0].asset.text == "A" * 30


def test_create_rsa_rejects_unbalanced_braces() -> None:
    client = _FakeClient()
    result = mutations.create_responsive_search_ad(
        client,
        ad_group_id="7",
        final_url="https://x.test/",
        headlines=["{KeyWord:Foo"],
        descriptions=["d"],
    )
    assert not result.ok
    assert "unbalanced" in result.partial_errors[0]
    assert client.calls == []  # rejected before any API call


def test_update_rsa_rejects_unbalanced_braces() -> None:
    client = _FakeClient()
    result = mutations.update_responsive_search_ad(
        client, ad_group_id="7", ad_id="9", headlines=["{KeyWord:Foo"]
    )
    assert not result.ok and result.ids == ["9"]
    assert "unbalanced" in result.partial_errors[0]
    assert client.calls == []


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


def test_update_ad_group_sends_network() -> None:
    """Partial update sends id + Network only, with the correct API alias (issue 19)."""
    client = _FakeClient()
    result = mutations.update_ad_group(
        client, campaign_id="1", ad_group_id="7", network="OwnedAndOperatedOnly"
    )
    assert result.ok and result.ids == ["7"]
    _, method, request = client.calls[0]
    assert method == "update_ad_groups"
    assert request.campaign_id == "1"
    assert request.ad_groups[0].to_dict() == {"Id": "7", "Network": "OwnedAndOperatedOnly"}


def test_create_ad_group_sends_network() -> None:
    """A new (paused) ad group carries the requested ad distribution."""
    client = _ConstClient(SimpleNamespace(ad_group_ids=["7"]))
    result = mutations.create_ad_group(
        client, campaign_id="1", name="AG", network="OwnedAndOperatedOnly"
    )
    assert result.ok and result.ids == ["7"]
    ad_group = client.calls[0][2].ad_groups[0]
    assert ad_group.network == "OwnedAndOperatedOnly"
    assert ad_group.status == "Paused"  # new ad groups are created paused


def test_update_ad_group_rejects_bad_network() -> None:
    """Networks Microsoft rejects for Search ad groups are caught before any API call (iss. 19).

    "SyndicatedSearchOnly" returns CampaignServiceInvalidNetwork live, and on create it would even
    crash response parsing (null id) -- so we reject it (and "InHousePromotion") up front instead.
    """
    for bad in ("SyndicatedSearchOnly", "InHousePromotion"):
        client = _FakeClient()
        try:
            mutations.update_ad_group(client, campaign_id="1", ad_group_id="7", network=bad)
        except ValueError as exc:
            assert "OwnedAndOperatedAndSyndicatedSearch" in str(exc)
        else:  # pragma: no cover - the call must raise
            raise AssertionError(f"expected ValueError for invalid network {bad!r}")
        assert client.calls == []  # rejected before any API call


def test_add_keywords_null_id_surfaces_partial_error() -> None:
    # The original issue-9 repro: a duplicate keyword comes back as KeywordIds=[null] +
    # PartialErrors. call_raw + dict-aware helpers must surface the reason as ok=false, not crash on
    # the non-nullable id list. Script the raw JSON dict (Pascal keys) call_raw really returns.
    raw = {
        "KeywordIds": [None],
        "PartialErrors": [{"Code": "CampaignServiceDuplicateKeyword", "Message": "dup"}],
    }
    result = mutations.add_keywords(_ConstClient(raw), ad_group_id="7", keywords=["astound login"])
    assert result.ok is False and result.ids == []
    assert result.message == "Add keywords failed"
    assert result.partial_errors == ["CampaignServiceDuplicateKeyword: dup"]


def test_create_ad_group_null_id_surfaces_partial_error() -> None:
    # A rejected ad group returns AdGroupIds=[null] + PartialErrors; must degrade, not crash.
    raw = {
        "AdGroupIds": [None],
        "PartialErrors": [{"Code": "CampaignServiceInvalidNetwork", "Message": "bad network"}],
    }
    result = mutations.create_ad_group(_ConstClient(raw), campaign_id="1", name="AG")
    assert result.ok is False and result.ids == []
    assert result.message == "Ad group create failed"
    assert result.partial_errors == ["CampaignServiceInvalidNetwork: bad network"]
