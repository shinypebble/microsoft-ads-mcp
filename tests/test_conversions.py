"""Conversion-goal and UET-tag flows: rename via subtype rebuild, UET partial update."""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.conversion_goal import ConversionGoal

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


def test_update_uet_tag_partial() -> None:
    client = _ScriptedClient([type("R", (), {"partial_errors": None})()])
    result = conversions.update_uet_tag(client, tag_id="9", name="GCF UET")
    assert result.ok
    _, method, request = client.calls[0]
    assert method == "update_uet_tags"
    tag = request.uet_tags[0]
    assert tag.id == "9" and tag.name == "GCF UET"
    assert tag.description is None  # untouched field stays unset
