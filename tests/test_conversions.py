"""Conversion-goal and UET-tag flows: rename via subtype rebuild, UET partial update."""

from __future__ import annotations

from typing import Any

import pytest
from openapi_client.models.campaign.conversion_goal import ConversionGoal

from microsoft_ads_mcp.domain.entities import ConversionGoalSummary
from microsoft_ads_mcp.services import conversions


class _ScriptedClient:
    account_id = "123"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
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
