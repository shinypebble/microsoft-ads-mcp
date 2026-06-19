"""Geo postal-code indexing, location criterion building, and bulk entity mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from microsoft_ads_mcp.services import bulk, criteria, geo


def test_geo_index_parses_real_microsoft_format() -> None:
    # Real geo file: ZIP lives in the first pipe-segment of "Bing Display Name".
    csv_text = (
        "Location Id,Bing Display Name,Location Type,Replaces,Status,AdWords Location Id\n"
        "71326,98052|Washington|United States,PostalCode,,Active,9033288\n"
        "71327,98101|Washington|United States,PostalCode,,Active,9033289\n"
        "71328,99999|Old|United States,PostalCode,,PendingDeprecation,1\n"
        "190,United States,Country,,Active,2840\n"
    )
    index = geo._index_postal_codes(csv_text)
    assert index["98052"] == "71326" and index["98101"] == "71327"
    assert "99999" not in index  # PendingDeprecation skipped
    assert "UNITED STATES" not in index  # non-postal rows skipped


def test_geo_index_supports_explicit_code_column() -> None:
    csv_text = "Location Id,Name,Location Type,Status,Code\n111,Seattle,Postal Code,Active,98101\n"
    assert geo._index_postal_codes(csv_text)["98101"] == "111"


def test_geo_index_raises_on_bad_format() -> None:
    with pytest.raises(Exception, match="geo-locations file format"):
        geo._index_postal_codes("Foo,Bar\n1,2\n")


class _FakeClient:
    account_id = "123"

    def __init__(self, resp: Any) -> None:
        self._resp = resp
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        return self._resp


def test_add_location_targets_builds_biddable_criterion_with_discriminators() -> None:
    resp = SimpleNamespace(campaign_criterion_ids=["900"], nested_partial_errors=[])
    client = _FakeClient(resp)
    result = criteria.add_location_targets(
        client, campaign_id="487928625", location_ids=["111"], bid_adjustment=10.0
    )
    assert result.ok and result.ids == ["900"]
    _, method, request = client.calls[0]
    assert method == "add_campaign_criterions"
    assert request.criterion_type.name == "TARGETS"  # adds use the umbrella Targets type
    cc = request.campaign_criterions[0]
    assert cc.type == "BiddableCampaignCriterion" and cc.campaign_id == "487928625"
    assert cc.criterion.type == "LocationCriterion" and cc.criterion.location_id == "111"
    assert cc.criterion_bid.type == "BidMultiplier" and cc.criterion_bid.multiplier == 10.0


def test_add_location_targets_exclude_uses_negative_criterion() -> None:
    client = _FakeClient(SimpleNamespace(campaign_criterion_ids=["901"], nested_partial_errors=[]))
    criteria.add_location_targets(client, campaign_id="1", location_ids=["111"], exclude=True)
    cc = client.calls[0][2].campaign_criterions[0]
    assert cc.type == "NegativeCampaignCriterion"
    assert cc.criterion.location_id == "111"


def test_remove_location_targets_passes_criterion_type() -> None:
    client = _FakeClient(SimpleNamespace(partial_errors=[]))
    result = criteria.remove_location_targets(client, campaign_id="1", criterion_ids=["900"])
    assert result.ok and result.ids == ["900"]
    request = client.calls[0][2]
    assert request.criterion_type.name == "TARGETS"  # deletes use the umbrella Targets type
    assert request.campaign_criterion_ids == ["900"]


class _SequencedClient:
    """Returns queued responses in order (for flows that make several calls)."""

    account_id = "123"

    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        return self._responses.pop(0)


def _intent_criterion(intent: str) -> Any:
    crit = SimpleNamespace(type="LocationIntentCriterion", intent_option=intent)
    return SimpleNamespace(id="487928625", campaign_id="487928625", criterion=crit)


def test_get_location_intent_reads_current_option() -> None:
    resp = SimpleNamespace(campaign_criterions=[_intent_criterion("PeopleIn")])
    client = _FakeClient(resp)
    summary = criteria.get_location_intent(client, campaign_id="487928625")
    assert summary is not None
    assert summary.intent_option == "PeopleIn"
    assert summary.criterion_id == "487928625"
    request = client.calls[0][2]
    assert request.criterion_type.name == "LOCATIONINTENT"


def test_get_location_intent_returns_none_when_absent() -> None:
    client = _FakeClient(SimpleNamespace(campaign_criterions=[]))
    assert criteria.get_location_intent(client, campaign_id="1") is None


def test_set_location_intent_updates_existing_criterion() -> None:
    get_resp = SimpleNamespace(campaign_criterions=[_intent_criterion("PeopleIn")])
    update_resp = SimpleNamespace(nested_partial_errors=[])
    client = _SequencedClient(get_resp, update_resp)
    result = criteria.set_location_intent(
        client, campaign_id="487928625", intent_option="PeopleInOrSearchingForOrViewingPages"
    )
    assert result.ok and result.ids == ["487928625"]
    # First call reads (LocationIntent type), second call updates.
    get_request = client.calls[0][2]
    assert client.calls[0][1] == "get_campaign_criterions_by_ids"
    assert get_request.criterion_type.name == "LOCATIONINTENT"
    _, method, request = client.calls[1]
    assert method == "update_campaign_criterions"
    # Updates of target criterions (incl. location intent) must use the umbrella Targets type;
    # the specific LocationIntent type is only valid for the get filter (the API 400s otherwise).
    assert request.criterion_type.name == "TARGETS"
    cc = request.campaign_criterions[0]
    assert cc.type == "BiddableCampaignCriterion" and cc.id == "487928625"
    assert cc.criterion.type == "LocationIntentCriterion"
    assert cc.criterion.intent_option.value == "PeopleInOrSearchingForOrViewingPages"


def test_set_location_intent_adds_when_no_criterion_exists() -> None:
    # A campaign with no criterions yet has no location-intent criterion to update, so add one.
    get_resp = SimpleNamespace(campaign_criterions=[])
    add_resp = SimpleNamespace(campaign_criterion_ids=["555"], nested_partial_errors=[])
    client = _SequencedClient(get_resp, add_resp)
    result = criteria.set_location_intent(client, campaign_id="1", intent_option="PeopleIn")
    assert result.ok and result.ids == ["555"]
    _, method, request = client.calls[1]
    assert method == "add_campaign_criterions"
    assert request.criterion_type.name == "TARGETS"
    cc = request.campaign_criterions[0]
    assert cc.id is None and cc.criterion.intent_option.value == "PeopleIn"


def test_bulk_download_entities_mapping() -> None:
    members = bulk._download_entities(["Campaigns", "Keywords"])
    assert [m.name for m in members] == ["CAMPAIGNS", "KEYWORDS"]


def test_bulk_download_entities_default() -> None:
    members = bulk._download_entities(None)
    assert "CAMPAIGNS" in [m.name for m in members]


def test_bulk_download_entities_unknown_rejected() -> None:
    with pytest.raises(ValueError, match="unknown download entity"):
        bulk._download_entities(["Sandwiches"])
