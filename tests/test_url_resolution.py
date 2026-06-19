"""Effective URL-settings resolution: walk the inheritance chain and report the source level."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from microsoft_ads_mcp.services import url_resolution


class _ScriptedClient:
    """Returns queued responses in order, one per ``call`` (account -> campaign -> ad groups)."""

    account_id = "123"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        return self._responses.pop(0)


def _account(**props: str) -> Any:
    return SimpleNamespace(
        account_properties=[SimpleNamespace(name=k, value=v) for k, v in props.items()]
    )


def test_campaign_inherits_account_template() -> None:
    client = _ScriptedClient(
        [
            _account(
                TrackingUrlTemplate="{lpurl}?utm_source=bing", MSCLKIDAutoTaggingEnabled="true"
            ),
            SimpleNamespace(
                campaigns=[SimpleNamespace(id="487928625", name="GCF", status="Paused")]
            ),
        ]
    )
    out = url_resolution.get_effective_url_settings(client, campaign_id="487928625")
    assert out.level == "campaign" and out.campaign_id == "487928625"
    # The campaign's own template is null, so the effective value comes from the account.
    assert out.effective_tracking_url_template == "{lpurl}?utm_source=bing"
    assert out.tracking_url_template_source == "account"
    assert out.msclkid_auto_tagging_enabled is True
    # Nothing sets a suffix anywhere -> unset, no source.
    assert out.effective_final_url_suffix is None and out.final_url_suffix_source is None


def test_campaign_template_overrides_account() -> None:
    client = _ScriptedClient(
        [
            _account(TrackingUrlTemplate="ACCT"),
            SimpleNamespace(
                campaigns=[
                    SimpleNamespace(id="1", name="C", status="Paused", tracking_url_template="CAMP")
                ]
            ),
        ]
    )
    out = url_resolution.get_effective_url_settings(client, campaign_id="1")
    assert out.effective_tracking_url_template == "CAMP"
    assert out.tracking_url_template_source == "campaign"


def test_ad_group_override_wins_and_template_falls_back_to_campaign() -> None:
    client = _ScriptedClient(
        [
            _account(TrackingUrlTemplate="ACCT"),
            SimpleNamespace(
                campaigns=[
                    SimpleNamespace(id="1", name="C", status="Paused", tracking_url_template="CAMP")
                ]
            ),
            SimpleNamespace(
                ad_groups=[
                    SimpleNamespace(
                        id="7", name="AG", status="Paused", final_url_suffix="utm_id=7"
                    ),
                    SimpleNamespace(id="8", name="Other", status="Paused"),
                ]
            ),
        ]
    )
    out = url_resolution.get_effective_url_settings(client, campaign_id="1", ad_group_id="7")
    assert out.level == "ad_group" and out.ad_group_id == "7"
    # Ad group has no template -> inherits the campaign's; it has its own suffix -> that wins.
    assert out.effective_tracking_url_template == "CAMP"
    assert out.tracking_url_template_source == "campaign"
    assert out.effective_final_url_suffix == "utm_id=7"
    assert out.final_url_suffix_source == "ad_group"


def test_missing_campaign_raises() -> None:
    client = _ScriptedClient([_account(), SimpleNamespace(campaigns=[])])
    with pytest.raises(ValueError, match="Campaign 404 not found"):
        url_resolution.get_effective_url_settings(client, campaign_id="404")


def test_missing_ad_group_raises() -> None:
    client = _ScriptedClient(
        [
            _account(),
            SimpleNamespace(campaigns=[SimpleNamespace(id="1", name="C", status="Paused")]),
            SimpleNamespace(ad_groups=[]),
        ]
    )
    with pytest.raises(ValueError, match="Ad group 7 not found"):
        url_resolution.get_effective_url_settings(client, campaign_id="1", ad_group_id="7")
