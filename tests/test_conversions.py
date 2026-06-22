"""Conversion-goal and UET-tag flows: create, rename via subtype rebuild, UET partial update,
and offline-conversion import."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from openapi_client.models.campaign.conversion_goal import ConversionGoal

from microsoft_ads_mcp.domain.entities import ConversionGoalSummary, OfflineConversionInput
from microsoft_ads_mcp.services import conversions


class _ScriptedClient:
    account_id = "123"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        return self._responses.pop(0)

    def call_raw(self, service: str, method: str, request: Any) -> Any:
        # create_conversion_goal reads the raw JSON dict; tests script dicts for it.
        self.calls.append((service, method, request))
        return self._responses.pop(0)


def test_rename_conversion_goal_rebuilds_same_subtype_partial() -> None:
    # GET returns a concrete UrlGoal; the update must resend a minimal {Id, Type, Name}.
    url_goal = ConversionGoal.from_dict(
        {"Type": "Url", "Id": "777", "Name": "CMI - Website Call Click", "TagId": "555"}
    )
    fake_get = type("R", (), {"conversion_goals": [url_goal], "partial_errors": None})()
    fake_update = type("R", (), {"partial_errors": None})()
    client = _ScriptedClient([fake_get, fake_update])

    result = conversions.update_conversion_goal(
        client, goal_id="777", name="GCF - Website Call Click"
    )
    assert result.ok and result.ids == ["777"]
    assert [c[1] for c in client.calls] == [
        "get_conversion_goals_by_ids",
        "update_conversion_goals",
    ]
    sent = client.calls[1][2].conversion_goals[0]
    assert type(sent).__name__ == "UrlGoal"
    assert sent.to_dict() == {"Name": "GCF - Website Call Click", "Id": "777", "Type": sent.type}


def test_rename_missing_goal_reports_not_found() -> None:
    empty = type("R", (), {"conversion_goals": [], "partial_errors": None})()
    client = _ScriptedClient([empty])
    result = conversions.update_conversion_goal(client, goal_id="x", name="y")
    assert not result.ok and "not found" in result.message


def _scripted_for_update() -> _ScriptedClient:
    """A client whose GET returns one UrlGoal, then a clean update response."""
    url_goal = ConversionGoal.from_dict({"Type": "Url", "Id": "777", "Name": "Lead"})
    fake_get = type("R", (), {"conversion_goals": [url_goal], "partial_errors": None})()
    fake_update = type("R", (), {"partial_errors": None})()
    return _ScriptedClient([fake_get, fake_update])


def test_update_includes_goal_in_bidding_sends_false() -> None:
    # exclude_from_bidding=False is meaningful ("Include in conversions") and must be sent, not
    # dropped as falsy.
    client = _scripted_for_update()
    result = conversions.update_conversion_goal(client, goal_id="777", exclude_from_bidding=False)
    assert result.ok and result.ids == ["777"]
    sent = client.calls[1][2].conversion_goals[0]
    assert sent.to_dict() == {"Id": "777", "Type": sent.type, "ExcludeFromBidding": False}


def test_update_sets_status_count_type_and_window() -> None:
    client = _scripted_for_update()
    result = conversions.update_conversion_goal(
        client,
        goal_id="777",
        status="Paused",
        count_type="Unique",
        conversion_window_in_minutes=43200,
    )
    assert result.ok
    sent = client.calls[1][2].conversion_goals[0]
    assert sent.to_dict() == {
        "Id": "777",
        "Type": sent.type,
        "Status": "Paused",
        "CountType": "Unique",
        "ConversionWindowInMinutes": 43200,
    }


def test_update_sets_revenue() -> None:
    client = _scripted_for_update()
    result = conversions.update_conversion_goal(
        client,
        goal_id="777",
        revenue_type="FixedValue",
        revenue_value=12.5,
        revenue_currency_code="USD",
    )
    assert result.ok
    sent = client.calls[1][2].conversion_goals[0]
    assert sent.to_dict() == {
        "Id": "777",
        "Type": sent.type,
        "Revenue": {"Type": "FixedValue", "Value": 12.5, "CurrencyCode": "USD"},
    }


def _scripted_with_revenue() -> _ScriptedClient:
    """A client whose GET returns a FixedValue goal worth 10 USD, then a clean update response."""
    goal = ConversionGoal.from_dict(
        {
            "Type": "Url",
            "Id": "777",
            "Name": "Lead",
            "Revenue": {"Type": "FixedValue", "Value": 10.0, "CurrencyCode": "USD"},
        }
    )
    fake_get = type("R", (), {"conversion_goals": [goal], "partial_errors": None})()
    fake_update = type("R", (), {"partial_errors": None})()
    return _ScriptedClient([fake_get, fake_update])


def test_update_revenue_merges_existing_subfields() -> None:
    # Bumping only the amount must NOT null out the goal's existing Type/CurrencyCode (the API
    # replaces Revenue wholesale, so we re-send the merged sub-fields).
    client = _scripted_with_revenue()
    result = conversions.update_conversion_goal(client, goal_id="777", revenue_value=20.0)
    assert result.ok
    sent = client.calls[1][2].conversion_goals[0]
    assert sent.to_dict() == {
        "Id": "777",
        "Type": sent.type,
        "Revenue": {"Type": "FixedValue", "Value": 20.0, "CurrencyCode": "USD"},
    }


def test_update_revenue_novalue_sends_type_only() -> None:
    # Switching to NoValue must drop the inherited Value/CurrencyCode (NoValue forbids a Value).
    client = _scripted_with_revenue()
    result = conversions.update_conversion_goal(client, goal_id="777", revenue_type="NoValue")
    assert result.ok
    sent = client.calls[1][2].conversion_goals[0]
    assert sent.to_dict() == {"Id": "777", "Type": sent.type, "Revenue": {"Type": "NoValue"}}


def test_update_revenue_value_without_type_or_existing_raises() -> None:
    # A goal with no existing revenue + a value but no type can't form a valid Revenue.
    client = _scripted_for_update()
    with pytest.raises(ValueError, match="revenue_type is required"):
        conversions.update_conversion_goal(client, goal_id="777", revenue_value=5.0)


def test_update_fixedvalue_without_value_raises() -> None:
    client = _scripted_for_update()
    with pytest.raises(ValueError, match="revenue_value is required"):
        conversions.update_conversion_goal(client, goal_id="777", revenue_type="FixedValue")


def test_update_rejects_bad_status() -> None:
    client = _scripted_for_update()
    with pytest.raises(ValueError, match="Active"):
        conversions.update_conversion_goal(client, goal_id="777", status="Enabled")


def test_update_requires_at_least_one_field() -> None:
    client = _scripted_for_update()
    with pytest.raises(ValueError, match="at least one field"):
        conversions.update_conversion_goal(client, goal_id="777")


def test_conversion_goal_summary_surfaces_bidding_fields() -> None:
    goal = ConversionGoal.from_dict(
        {
            "Type": "Url",
            "Id": "777",
            "Name": "Lead",
            "Status": "Active",
            "TagId": "555",
            "ExcludeFromBidding": False,
            "CountType": "Unique",
            "ConversionWindowInMinutes": 43200,
            "GoalCategory": "SubmitLeadForm",
            "Revenue": {"Type": "FixedValue", "Value": 12.5, "CurrencyCode": "USD"},
        }
    )
    summary = ConversionGoalSummary.from_sdk(goal)
    assert summary.exclude_from_bidding is False
    assert summary.count_type == "Unique"
    assert summary.conversion_window_in_minutes == 43200
    assert summary.goal_category == "SubmitLeadForm"
    assert summary.revenue_type == "FixedValue"
    assert summary.revenue_value == 12.5
    assert summary.revenue_currency_code == "USD"


def test_update_uet_tag_partial() -> None:
    client = _ScriptedClient([type("R", (), {"partial_errors": None})()])
    result = conversions.update_uet_tag(client, tag_id="9", name="GCF UET")
    assert result.ok
    _, method, request = client.calls[0]
    assert method == "update_uet_tags"
    tag = request.uet_tags[0]
    assert tag.id == "9" and tag.name == "GCF UET"
    assert tag.description is None  # untouched field stays unset


# --- create_conversion_goal -------------------------------------------------------------------


def _create_resp(ids: list[str | None] | None = None, errors: list[Any] | None = None) -> dict:
    # create_conversion_goal reads the raw JSON via call_raw, so script the dict Microsoft sends.
    return {"ConversionGoalIds": ids, "PartialErrors": errors}


def test_create_offline_conversion_goal_builds_offline_subtype() -> None:
    # Offline goals key on MSCLKID: no UET TagId, and no Id in the request (the API assigns it).
    client = _ScriptedClient([_create_resp(["999"])])
    result = conversions.create_conversion_goal(
        client, name="Qualified Calls", goal_type="OfflineConversion"
    )
    assert result.ok and result.ids == ["999"]
    _, method, request = client.calls[0]
    assert method == "add_conversion_goals"
    sent = request.conversion_goals[0]
    assert type(sent).__name__ == "OfflineConversionGoal"
    d = sent.to_dict()
    assert d == {"Name": "Qualified Calls", "Type": sent.type}
    assert "TagId" not in d and "Id" not in d


def test_create_url_goal_with_tag_and_revenue() -> None:
    client = _ScriptedClient([_create_resp(["111"])])
    result = conversions.create_conversion_goal(
        client,
        name="Lead",
        goal_type="Url",
        tag_id="555",
        url_expression="contact/thanks",
        url_operator="Contains",
        revenue_type="FixedValue",
        revenue_value=12.5,
        revenue_currency_code="USD",
    )
    assert result.ok and result.ids == ["111"]
    sent = client.calls[0][2].conversion_goals[0]
    assert type(sent).__name__ == "UrlGoal"
    d = sent.to_dict()
    assert d == {
        "Name": "Lead",
        "Type": sent.type,
        "TagId": "555",
        "Revenue": {"Type": "FixedValue", "Value": 12.5, "CurrencyCode": "USD"},
        "UrlExpression": "contact/thanks",
        "UrlOperator": sent.url_operator,
    }


def test_create_event_goal_sets_expression_fields() -> None:
    client = _ScriptedClient([_create_resp(["222"])])
    result = conversions.create_conversion_goal(
        client,
        name="Video Play",
        goal_type="Event",
        tag_id="555",
        category_expression="video",
        category_operator="Equals",
        action_expression="play",
        action_operator="Equals",
        value=5.0,
        value_operator="GreaterThan",
    )
    assert result.ok
    sent = client.calls[0][2].conversion_goals[0]
    assert type(sent).__name__ == "EventGoal"
    d = sent.to_dict()
    assert d["CategoryExpression"] == "video"
    assert d["ActionExpression"] == "play"
    assert d["Value"] == 5.0
    assert d["TagId"] == "555"


def test_create_duration_goal_sets_minimum() -> None:
    client = _ScriptedClient([_create_resp(["333"])])
    result = conversions.create_conversion_goal(
        client,
        name="Dwell 60s",
        goal_type="Duration",
        tag_id="555",
        minimum_duration_in_seconds=60,
    )
    assert result.ok
    sent = client.calls[0][2].conversion_goals[0]
    assert type(sent).__name__ == "DurationGoal"
    assert sent.to_dict()["MinimumDurationInSeconds"] == 60


def test_create_pages_viewed_goal_sets_minimum() -> None:
    client = _ScriptedClient([_create_resp(["444"])])
    result = conversions.create_conversion_goal(
        client,
        name="3+ pages",
        goal_type="PagesViewedPerVisit",
        tag_id="555",
        minimum_pages_viewed=3,
    )
    assert result.ok
    sent = client.calls[0][2].conversion_goals[0]
    assert type(sent).__name__ == "PagesViewedPerVisitGoal"
    assert sent.to_dict()["MinimumPagesViewed"] == 3


def test_create_web_goal_without_tag_id_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="tag_id"):
        conversions.create_conversion_goal(client, name="Lead", goal_type="Url", url_expression="x")


def test_create_offline_goal_with_tag_id_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="tag_id"):
        conversions.create_conversion_goal(
            client, name="Calls", goal_type="OfflineConversion", tag_id="555"
        )


def test_create_url_goal_missing_url_expression_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="url_expression"):
        conversions.create_conversion_goal(client, name="Lead", goal_type="Url", tag_id="555")


def test_create_goal_rejects_mismatched_type_field() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="only valid for PagesViewedPerVisit"):
        conversions.create_conversion_goal(
            client,
            name="Lead",
            goal_type="Url",
            tag_id="555",
            url_expression="x",
            minimum_pages_viewed=3,
        )


def test_create_goal_unknown_type_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="goal_type must be"):
        conversions.create_conversion_goal(client, name="x", goal_type="Bogus")


def test_create_goal_fixedvalue_without_value_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="revenue_value is required"):
        conversions.create_conversion_goal(
            client, name="Calls", goal_type="OfflineConversion", revenue_type="FixedValue"
        )


def test_create_goal_revenue_value_without_type_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="revenue_type is required"):
        conversions.create_conversion_goal(
            client, name="Calls", goal_type="OfflineConversion", revenue_value=5.0
        )


def test_create_goal_partial_errors() -> None:
    err = type("E", (), {"message": "dup", "code": 4001})()
    client = _ScriptedClient([_create_resp(None, [err])])
    result = conversions.create_conversion_goal(client, name="Calls", goal_type="OfflineConversion")
    assert not result.ok and result.ids == []
    assert result.partial_errors == ["4001: dup"]


def test_create_goal_null_id_surfaces_partial_error() -> None:
    # Microsoft returns HTTP 200 with ConversionGoalIds=[null] + PartialErrors when a goal is
    # rejected. call_raw + dict-aware first_attr must surface the error cleanly (no crash, no
    # phantom id) instead of the SDK's non-nullable-string deserialization blowing up.
    resp = {
        "ConversionGoalIds": [None],
        "PartialErrors": [
            {
                "ErrorCode": "InvalidGoalCategory",
                "Message": "The Goal Category is invalid.",
                "Code": 3347,
            }
        ],
    }
    client = _ScriptedClient([resp])
    result = conversions.create_conversion_goal(
        client, name="Bad", goal_type="Event", tag_id="555", category_expression="x"
    )
    assert not result.ok and result.ids == []
    assert result.partial_errors == ["InvalidGoalCategory: The Goal Category is invalid."]


def test_create_goal_defaults_to_active() -> None:
    # A goal doesn't spend, so the default is active; we never send Status=Paused.
    client = _ScriptedClient([_create_resp(["999"])])
    conversions.create_conversion_goal(client, name="Calls", goal_type="OfflineConversion")
    assert "Status" not in client.calls[0][2].conversion_goals[0].to_dict()


def test_create_goal_exclude_from_bidding_false_is_sent() -> None:
    client = _ScriptedClient([_create_resp(["999"])])
    conversions.create_conversion_goal(
        client, name="Calls", goal_type="OfflineConversion", exclude_from_bidding=False
    )
    assert client.calls[0][2].conversion_goals[0].to_dict()["ExcludeFromBidding"] is False


# --- apply_offline_conversions ----------------------------------------------------------------


def test_apply_offline_conversions_builds_request() -> None:
    client = _ScriptedClient([type("R", (), {"partial_errors": None})()])
    result = conversions.apply_offline_conversions(
        client,
        conversions=[
            OfflineConversionInput(
                click_id="CLICK123",
                conversion_name="Qualified Calls",
                conversion_time="2026-06-01T12:00:00+00:00",
                value=40.0,
                currency_code="USD",
            )
        ],
    )
    assert result.ok and result.ids == []
    _, method, request = client.calls[0]
    assert method == "apply_offline_conversions"
    sent = request.offline_conversions[0]
    assert type(sent).__name__ == "OfflineConversion"
    assert sent.microsoft_click_id == "CLICK123"
    assert sent.conversion_name == "Qualified Calls"
    assert sent.conversion_value == 40.0
    assert sent.conversion_currency_code == "USD"
    assert isinstance(sent.conversion_time, datetime)


def test_apply_offline_conversion_naive_time_is_utc() -> None:
    client = _ScriptedClient([type("R", (), {"partial_errors": None})()])
    conversions.apply_offline_conversions(
        client,
        conversions=[
            OfflineConversionInput(
                click_id="C", conversion_name="Calls", conversion_time="2026-06-01T12:00:00"
            )
        ],
    )
    sent = client.calls[0][2].offline_conversions[0]
    assert sent.conversion_time.tzinfo == UTC


def test_apply_offline_conversion_offset_time_preserved() -> None:
    client = _ScriptedClient([type("R", (), {"partial_errors": None})()])
    conversions.apply_offline_conversions(
        client,
        conversions=[
            OfflineConversionInput(
                click_id="C",
                conversion_name="Calls",
                conversion_time="2026-06-01T08:00:00-04:00",
            )
        ],
    )
    sent = client.calls[0][2].offline_conversions[0]
    assert sent.conversion_time.utcoffset() == timedelta(hours=-4)


def test_apply_offline_conversions_bad_time_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="ISO-8601"):
        conversions.apply_offline_conversions(
            client,
            conversions=[
                OfflineConversionInput(
                    click_id="C", conversion_name="Calls", conversion_time="June 1, 2026"
                )
            ],
        )


def test_apply_offline_conversions_empty_list_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="at least one"):
        conversions.apply_offline_conversions(client, conversions=[])


def test_apply_offline_conversions_value_without_currency_raises() -> None:
    client = _ScriptedClient([])
    with pytest.raises(ValueError, match="currency_code is required"):
        conversions.apply_offline_conversions(
            client,
            conversions=[
                OfflineConversionInput(
                    click_id="C",
                    conversion_name="Calls",
                    conversion_time="2026-06-01T12:00:00Z",
                    value=10.0,
                )
            ],
        )


def test_apply_offline_conversions_partial_errors() -> None:
    err = type("E", (), {"message": "bad msclkid", "code": 5001})()
    client = _ScriptedClient([type("R", (), {"partial_errors": [err]})()])
    result = conversions.apply_offline_conversions(
        client,
        conversions=[
            OfflineConversionInput(
                click_id="C", conversion_name="Calls", conversion_time="2026-06-01T12:00:00Z"
            )
        ],
    )
    assert not result.ok and result.ids == []
    assert result.partial_errors == ["5001: bad msclkid"]
