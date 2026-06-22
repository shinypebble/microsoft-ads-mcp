"""Geo postal-code indexing, location criterion building, and bulk entity mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from microsoft_ads_mcp.domain.entities import AdScheduleInput
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

    # Add* paths read the raw JSON via call_raw; the dict-or-object-tolerant first_attr reads the
    # scripted response the same either way, so delegate to the same fixed response.
    def call_raw(self, service: str, method: str, request: Any) -> Any:
        return self.call(service, method, request)


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

    # Add* paths read the raw JSON via call_raw; first_attr reads the queued response the same
    # whether it is a dict or an object, so pull from the same queue.
    def call_raw(self, service: str, method: str, request: Any) -> Any:
        return self.call(service, method, request)


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


def _daytime_criterion(criterion_id: str, day: str) -> Any:
    crit = SimpleNamespace(
        type="DayTimeCriterion",
        day=day,
        from_hour=9,
        from_minute=SimpleNamespace(value="Fifteen"),
        to_hour=16,
        to_minute=SimpleNamespace(value="FortyFive"),
    )
    bid = SimpleNamespace(type="BidMultiplier", multiplier=0.0)
    return SimpleNamespace(
        id=criterion_id, campaign_id="487928625", criterion=crit, criterion_bid=bid
    )


def _campaign(campaign_id: str, time_zone: str, searcher: bool) -> Any:
    return SimpleNamespace(
        id=campaign_id,
        name="C",
        status="Active",
        campaign_type="Search",
        time_zone=time_zone,
        ad_schedule_use_searcher_time_zone=searcher,
    )


def test_get_ad_schedules_reads_windows_and_time_zone_context() -> None:
    daytime_resp = SimpleNamespace(
        campaign_criterions=[
            _daytime_criterion("901", "Monday"),
            _daytime_criterion("902", "Tuesday"),
        ]
    )
    campaigns_resp = SimpleNamespace(
        campaigns=[_campaign("487928625", "CentralTimeUSCanada", False)]
    )
    client = _SequencedClient(daytime_resp, campaigns_resp)
    settings = criteria.get_ad_schedules(client, campaign_id="487928625")
    assert settings.time_zone == "CentralTimeUSCanada"
    assert settings.use_searcher_time_zone is False
    assert [w.day for w in settings.schedules] == ["Monday", "Tuesday"]
    w = settings.schedules[0]
    assert (w.from_hour, w.from_minute, w.to_hour, w.to_minute) == (9, 15, 16, 45)
    assert w.criterion_id == "901" and w.bid_adjustment == 0.0
    # The DayTime criterions are read with the specific LocationIntent-style DayTime filter.
    assert client.calls[0][1] == "get_campaign_criterions_by_ids"
    assert client.calls[0][2].criterion_type.name == "DAYTIME"
    # Time-zone context is fetched for just this campaign, not by scanning the whole account.
    assert client.calls[1][1] == "get_campaigns_by_ids"
    assert client.calls[1][2].campaign_ids == ["487928625"]


def test_add_ad_schedules_builds_daytime_criterions_under_targets() -> None:
    add_resp = SimpleNamespace(campaign_criterion_ids=["1", "2"], nested_partial_errors=[])
    client = _FakeClient(add_resp)
    schedules = [
        AdScheduleInput(day="Monday", from_hour=9, from_minute=15, to_hour=16, to_minute=45),
        AdScheduleInput(
            day="Saturday",
            from_hour=9,
            from_minute=15,
            to_hour=16,
            to_minute=45,
            bid_adjustment=10.0,
        ),
    ]
    result = criteria.add_ad_schedules(client, campaign_id="487928625", schedules=schedules)
    assert result.ok and result.ids == ["1", "2"]
    _, method, request = client.calls[0]
    assert method == "add_campaign_criterions"
    # Adds of target criterions (incl. day/time) must use the umbrella Targets type.
    assert request.criterion_type.name == "TARGETS"
    cc0 = request.campaign_criterions[0]
    assert cc0.type == "BiddableCampaignCriterion" and cc0.campaign_id == "487928625"
    assert cc0.criterion.type == "DayTimeCriterion"
    assert cc0.criterion.day.value == "Monday"
    assert (
        cc0.criterion.from_minute.value == "Fifteen"
        and cc0.criterion.to_minute.value == "FortyFive"
    )
    assert cc0.criterion_bid is None  # no bid adjustment -> omitted
    cc1 = request.campaign_criterions[1]
    assert cc1.criterion_bid.type == "BidMultiplier" and cc1.criterion_bid.multiplier == 10.0


def test_add_ad_schedules_sets_searcher_time_zone_flag_after_add() -> None:
    add_resp = SimpleNamespace(campaign_criterion_ids=["1"], nested_partial_errors=[])
    tz_resp = SimpleNamespace(partial_errors=[])
    client = _SequencedClient(add_resp, tz_resp)
    schedules = [AdScheduleInput(day="Monday", from_hour=0, to_hour=24)]
    result = criteria.add_ad_schedules(
        client, campaign_id="1", schedules=schedules, use_searcher_time_zone=True
    )
    assert result.ok
    # The windows are added first; the campaign flag is only flipped once they land.
    assert client.calls[0][1] == "add_campaign_criterions"
    assert client.calls[1][1] == "update_campaigns"
    assert client.calls[1][2].campaigns[0].ad_schedule_use_searcher_time_zone is True


def test_add_ad_schedules_leaves_time_zone_flag_unchanged_when_add_fails() -> None:
    # The add returns partial errors and no ids -> creation failed.
    add_resp = SimpleNamespace(
        campaign_criterion_ids=[], nested_partial_errors=[SimpleNamespace(message="bad")]
    )
    client = _FakeClient(add_resp)
    schedules = [AdScheduleInput(day="Monday", from_hour=0, to_hour=24)]
    result = criteria.add_ad_schedules(
        client, campaign_id="1", schedules=schedules, use_searcher_time_zone=True
    )
    assert not result.ok
    # Only the add was attempted; the campaign time-zone flag was never touched.
    assert [c[1] for c in client.calls] == ["add_campaign_criterions"]


def test_add_ad_schedules_rejects_off_grid_minute() -> None:
    client = _FakeClient(SimpleNamespace(campaign_criterion_ids=[], nested_partial_errors=[]))
    with pytest.raises(ValueError, match="15-minute granularity"):
        criteria.add_ad_schedules(
            client,
            campaign_id="1",
            schedules=[AdScheduleInput(day="Monday", from_hour=9, from_minute=10, to_hour=17)],
        )


def test_add_ad_schedules_off_grid_minute_does_not_touch_time_zone_flag() -> None:
    # An off-grid minute must fail during validation, before any API call (so the time-zone flag
    # cannot be flipped even when use_searcher_time_zone is requested alongside the bad input).
    client = _FakeClient(SimpleNamespace(campaign_criterion_ids=[], nested_partial_errors=[]))
    with pytest.raises(ValueError, match="15-minute granularity"):
        criteria.add_ad_schedules(
            client,
            campaign_id="1",
            schedules=[AdScheduleInput(day="Monday", from_hour=9, from_minute=10, to_hour=17)],
            use_searcher_time_zone=True,
        )
    assert client.calls == []


def test_remove_ad_schedules_passes_targets_type() -> None:
    client = _FakeClient(SimpleNamespace(partial_errors=[]))
    result = criteria.remove_ad_schedules(client, campaign_id="1", criterion_ids=["901", "902"])
    assert result.ok and result.ids == ["901", "902"]
    request = client.calls[0][2]
    assert request.criterion_type.name == "TARGETS"
    assert request.campaign_criterion_ids == ["901", "902"]


def test_add_ad_schedules_null_id_surfaces_partial_error() -> None:
    # Microsoft returns HTTP 200 with CampaignCriterionIds=[null] + NestedPartialErrors when a
    # window is rejected (e.g. it overlaps an existing same-day window). call_raw + dict-aware
    # first_attr must surface the reason cleanly, not crash on the non-nullable id list. Script the
    # raw JSON dict (Pascal keys) that call_raw really returns.
    raw = {
        "CampaignCriterionIds": [None],
        "NestedPartialErrors": [
            {
                "BatchErrors": [
                    {
                        "Code": "CampaignServiceAdScheduleOverlaps",
                        "Message": "overlaps an existing schedule",
                    }
                ]
            }
        ],
    }
    client = _FakeClient(raw)
    result = criteria.add_ad_schedules(
        client,
        campaign_id="1",
        schedules=[
            AdScheduleInput(day="Monday", from_hour=9, from_minute=15, to_hour=19, to_minute=45)
        ],
    )
    assert result.ok is False
    assert result.ids == []
    assert result.partial_errors == [
        "CampaignServiceAdScheduleOverlaps: overlaps an existing schedule"
    ]


def test_add_location_targets_null_id_surfaces_partial_error() -> None:
    # Same rejected-criterion shape for location targets: a null id must degrade to a partial error.
    raw = {
        "CampaignCriterionIds": [None],
        "NestedPartialErrors": [
            {"BatchErrors": [{"Code": "DuplicateInRequest", "Message": "dup"}]}
        ],
    }
    client = _FakeClient(raw)
    result = criteria.add_location_targets(client, campaign_id="1", location_ids=["111"])
    assert result.ok is False and result.ids == []
    assert result.partial_errors == ["DuplicateInRequest: dup"]


def test_replace_ad_schedule_removes_then_adds() -> None:
    remove_resp = SimpleNamespace(partial_errors=[])
    add_resp = SimpleNamespace(campaign_criterion_ids=["55"], nested_partial_errors=[])
    client = _SequencedClient(remove_resp, add_resp)
    new_window = AdScheduleInput(
        day="Monday", from_hour=9, from_minute=15, to_hour=19, to_minute=45
    )
    result = criteria.replace_ad_schedule(
        client, campaign_id="1", criterion_id="901", new_window=new_window
    )
    assert result.ok and result.ids == ["55"]
    # The remove must precede the add -- adding the overlapping window first is rejected by the API.
    assert client.calls[0][1] == "delete_campaign_criterions"
    assert client.calls[0][2].campaign_criterion_ids == ["901"]
    assert client.calls[1][1] == "add_campaign_criterions"
    cc = client.calls[1][2].campaign_criterions[0]
    assert cc.criterion.day.value == "Monday" and cc.criterion.from_hour == 9


def test_replace_ad_schedule_remove_failure_short_circuits() -> None:
    # If the remove fails, nothing is destroyed and the add is never attempted.
    remove_resp = SimpleNamespace(partial_errors=[SimpleNamespace(code="X", message="nope")])
    client = _SequencedClient(remove_resp)
    new_window = AdScheduleInput(day="Monday", from_hour=9, to_hour=19)
    result = criteria.replace_ad_schedule(
        client, campaign_id="1", criterion_id="901", new_window=new_window
    )
    assert not result.ok
    assert [c[1] for c in client.calls] == ["delete_campaign_criterions"]


def test_replace_ad_schedule_add_failure_after_remove_reports_gap() -> None:
    # Remove succeeds but the new window is rejected -> the old window is already gone; the result
    # must say so (so the caller knows coverage is dropped) and surface the add's partial errors.
    remove_resp = SimpleNamespace(partial_errors=[])
    add_resp = SimpleNamespace(
        campaign_criterion_ids=[None],
        nested_partial_errors=[
            SimpleNamespace(
                batch_errors=[SimpleNamespace(code="AdScheduleOverlaps", message="overlaps")]
            )
        ],
    )
    client = _SequencedClient(remove_resp, add_resp)
    new_window = AdScheduleInput(day="Monday", from_hour=9, to_hour=19)
    result = criteria.replace_ad_schedule(
        client, campaign_id="1", criterion_id="901", new_window=new_window
    )
    assert result.ok is False and result.ids == []
    assert "removed" in result.message.lower() and "re-add" in result.message.lower()
    assert any("overlaps" in e.lower() for e in result.partial_errors)
    assert [c[1] for c in client.calls] == [
        "delete_campaign_criterions",
        "add_campaign_criterions",
    ]


def test_replace_ad_schedule_tz_flag_failure_keeps_added_window() -> None:
    # The new window IS added but the optional time-zone-flag update fails -> add_ad_schedules
    # returns ok=False yet carries the real id. replace must NOT report this as "re-add it" (the
    # window exists); it passes the accurate result through with the new id intact.
    remove_resp = SimpleNamespace(partial_errors=[])
    add_resp = SimpleNamespace(campaign_criterion_ids=["55"], nested_partial_errors=[])
    tz_resp = SimpleNamespace(partial_errors=[SimpleNamespace(code="TzBad", message="tz failed")])
    client = _SequencedClient(remove_resp, add_resp, tz_resp)
    new_window = AdScheduleInput(day="Monday", from_hour=9, to_hour=19)
    result = criteria.replace_ad_schedule(
        client,
        campaign_id="1",
        criterion_id="901",
        new_window=new_window,
        use_searcher_time_zone=True,
    )
    assert result.ok is False
    assert result.ids == ["55"]  # the added window's id is preserved, not dropped
    assert "re-add" not in result.message.lower()  # not the false "window missing" message
    assert "time-zone" in result.message.lower()
    assert any("tz failed" in e.lower() for e in result.partial_errors)
    assert [c[1] for c in client.calls] == [
        "delete_campaign_criterions",
        "add_campaign_criterions",
        "update_campaigns",
    ]


def _device_criterion(criterion_id: str, device: str, multiplier: float = 0.0) -> Any:
    crit = SimpleNamespace(type="DeviceCriterion", device_name=device, os_name=None)
    bid = SimpleNamespace(type="BidMultiplier", multiplier=multiplier)
    return SimpleNamespace(
        id=criterion_id, campaign_id="487928625", criterion=crit, criterion_bid=bid
    )


def test_get_device_bid_adjustments_reads_devices() -> None:
    resp = SimpleNamespace(
        campaign_criterions=[
            _device_criterion("11", "Computers", 0.0),
            _device_criterion("12", "Smartphones", 40.0),
            _device_criterion("13", "Tablets", -100.0),
        ]
    )
    client = _FakeClient(resp)
    rows = criteria.get_device_bid_adjustments(client, campaign_id="487928625")
    assert [r.device for r in rows] == ["Computers", "Smartphones", "Tablets"]
    mobile = next(r for r in rows if r.device == "Smartphones")
    assert mobile.bid_adjustment == 40.0 and mobile.criterion_id == "12"
    assert client.calls[0][1] == "get_campaign_criterions_by_ids"
    assert client.calls[0][2].criterion_type.name == "DEVICE"  # read uses the specific Device type


def test_set_device_bid_adjustment_updates_existing_in_place() -> None:
    # All three device criterions already exist -> the target is updated in place (under Targets),
    # and "mobile" resolves to Microsoft's "Smartphones".
    get_resp = SimpleNamespace(
        campaign_criterions=[
            _device_criterion("11", "Computers"),
            _device_criterion("12", "Smartphones"),
            _device_criterion("13", "Tablets"),
        ]
    )
    update_resp = SimpleNamespace(nested_partial_errors=[])
    client = _SequencedClient(get_resp, update_resp)
    result = criteria.set_device_bid_adjustment(
        client, campaign_id="487928625", device="mobile", bid_adjustment=40.0
    )
    assert result.ok and result.ids == ["12"]
    assert client.calls[0][1] == "get_campaign_criterions_by_ids"
    _, method, request = client.calls[1]
    assert method == "update_campaign_criterions"
    assert request.criterion_type.name == "TARGETS"  # updates use the umbrella Targets type
    cc = request.campaign_criterions[0]
    assert cc.id == "12" and cc.criterion.type == "DeviceCriterion"
    assert cc.criterion.device_name == "Smartphones"
    assert cc.criterion_bid.type == "BidMultiplier" and cc.criterion_bid.multiplier == 40.0


def test_set_device_bid_adjustment_adds_all_three_when_none_exist() -> None:
    # A campaign with no device criterions: Microsoft requires the set, so all three are added
    # together, the target carrying the multiplier and the others a neutral 0.
    get_resp = SimpleNamespace(campaign_criterions=[])
    add_resp = SimpleNamespace(campaign_criterion_ids=["21", "22", "23"], nested_partial_errors=[])
    client = _SequencedClient(get_resp, add_resp)
    result = criteria.set_device_bid_adjustment(
        client, campaign_id="1", device="Smartphones", bid_adjustment=30.0
    )
    assert result.ok and result.ids == ["21", "22", "23"]
    _, method, request = client.calls[1]
    assert method == "add_campaign_criterions"
    assert request.criterion_type.name == "TARGETS"
    by_device = {
        cc.criterion.device_name: cc.criterion_bid.multiplier for cc in request.campaign_criterions
    }
    assert by_device == {"Computers": 0.0, "Smartphones": 30.0, "Tablets": 0.0}


def test_set_device_bid_adjustment_rejects_out_of_range() -> None:
    client = _FakeClient(SimpleNamespace(campaign_criterions=[]))
    with pytest.raises(ValueError, match="between -100 and 900"):
        criteria.set_device_bid_adjustment(
            client, campaign_id="1", device="Smartphones", bid_adjustment=950
        )


def test_set_device_bid_adjustment_rejects_unknown_device() -> None:
    client = _FakeClient(SimpleNamespace(campaign_criterions=[]))
    with pytest.raises(ValueError, match="Computers, Smartphones, Tablets"):
        criteria.set_device_bid_adjustment(
            client, campaign_id="1", device="Smartwatch", bid_adjustment=10
        )


def test_set_device_bid_adjustment_tool_schema_accepts_aliases() -> None:
    # Regression: the device param must NOT be a strict enum in the tool schema, or aliases like
    # "mobile" are rejected by input validation before the handler can normalize them.
    import asyncio

    from microsoft_ads_mcp.config import Settings
    from microsoft_ads_mcp.server import create_server

    settings = Settings(
        developer_token="d", client_id="c", refresh_token="r", account_id="1", read_only=False
    )
    tools = asyncio.run(create_server(settings).list_tools())
    tool = next(t for t in tools if t.name == "set_device_bid_adjustment")
    device_schema = tool.parameters["properties"]["device"]
    assert device_schema["type"] == "string"
    assert "enum" not in device_schema  # a strict enum would block the documented aliases


def test_bulk_download_entities_mapping() -> None:
    members = bulk._download_entities(["Campaigns", "Keywords"])
    assert [m.name for m in members] == ["CAMPAIGNS", "KEYWORDS"]


def test_bulk_download_entities_default() -> None:
    members = bulk._download_entities(None)
    assert "CAMPAIGNS" in [m.name for m in members]


def test_bulk_download_entities_unknown_rejected() -> None:
    with pytest.raises(ValueError, match="unknown download entity"):
        bulk._download_entities(["Sandwiches"])
