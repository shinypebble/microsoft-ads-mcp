"""Ad-extension flows: type-filter resolution, in-place call update, add+associate."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from microsoft_ads_mcp.services import extensions


class _ScriptedClient:
    """Returns queued responses in order, one per ``call``."""

    account_id = "123"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        return self._responses.pop(0)


def test_type_filter_resolves_friendly_names() -> None:
    f = extensions._type_filter(["Call", "Sitelink"])
    assert "CallAdExtension" in str(f) and "SitelinkAdExtension" in str(f)


def test_type_filter_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown ad extension type"):
        extensions._type_filter(["Telepathy"])


def test_get_ad_extensions_two_step_and_maps() -> None:
    client = _ScriptedClient(
        [
            SimpleNamespace(ad_extension_ids=["55"]),
            SimpleNamespace(
                ad_extensions=[
                    SimpleNamespace(
                        id="55",
                        type="CallAdExtension",
                        status="Active",
                        phone_number="2065551212",
                        country_code="US",
                    )
                ]
            ),
        ]
    )
    out = extensions.get_ad_extensions(client, association_type="Account")
    assert [c[1] for c in client.calls] == [
        "get_ad_extension_ids_by_account_id",
        "get_ad_extensions_by_ids",
    ]
    assert out[0].id == "55" and out[0].phone_number == "2065551212"


def test_get_ad_extensions_short_circuits_when_empty() -> None:
    client = _ScriptedClient([SimpleNamespace(ad_extension_ids=[])])
    assert extensions.get_ad_extensions(client, association_type="Account") == []
    assert len(client.calls) == 1  # never fetches details when there are no ids


def test_get_ad_extensions_default_enumerates_all_scopes_and_dedupes() -> None:
    # The default scope now sweeps Account + Campaign + AdGroup so campaign-attached extensions are
    # visible (the old Account-only default returned [] when extensions lived on the campaign). Ids
    # seen in more than one scope are de-duped before the single details fetch.
    client = _ScriptedClient(
        [
            SimpleNamespace(ad_extension_ids=[]),  # Account: none
            SimpleNamespace(ad_extension_ids=["55", "56"]),  # Campaign
            SimpleNamespace(ad_extension_ids=["55"]),  # AdGroup: dup of 55
            SimpleNamespace(
                ad_extensions=[
                    SimpleNamespace(id="55", type="CalloutAdExtension", status="Active"),
                    SimpleNamespace(id="56", type="SitelinkAdExtension", status="Active"),
                ]
            ),
        ]
    )
    out = extensions.get_ad_extensions(client)
    methods = [c[1] for c in client.calls]
    assert methods == [
        "get_ad_extension_ids_by_account_id",
        "get_ad_extension_ids_by_account_id",
        "get_ad_extension_ids_by_account_id",
        "get_ad_extensions_by_ids",
    ]
    # Each id-enumeration call targets a distinct scope, in order.
    assert [c[2].association_type for c in client.calls[:3]] == ["Account", "Campaign", "AdGroup"]
    # The details fetch receives de-duped ids (55 once, not twice).
    assert client.calls[3][2].ad_extension_ids == ["55", "56"]
    assert [e.id for e in out] == ["55", "56"]


def test_update_call_extension_is_partial_with_discriminator() -> None:
    client = _ScriptedClient([SimpleNamespace(nested_partial_errors=[])])
    result = extensions.update_call_extension(
        client, ad_extension_id="55", phone_number="8005550000", country_code="US"
    )
    assert result.ok and result.ids == ["55"]
    _, method, request = client.calls[0]
    assert method == "update_ad_extensions"
    ext = request.ad_extensions[0]
    assert ext.id == "55" and ext.type == "CallAdExtension"
    assert ext.phone_number == "8005550000" and ext.country_code == "US"


def test_update_call_extension_enables_call_tracking_merges_required_fields() -> None:
    # A tracking-only toggle must re-send phone/country (Microsoft replaces the whole object),
    # so the service first GETs the existing extension, then updates with the merged fields.
    client = _ScriptedClient(
        [
            SimpleNamespace(
                ad_extensions=[
                    SimpleNamespace(
                        id="8246425032469",
                        type="CallAdExtension",
                        phone_number="8555665900",
                        country_code="US",
                    )
                ]
            ),
            SimpleNamespace(nested_partial_errors=[]),
        ]
    )
    result = extensions.update_call_extension(
        client, ad_extension_id="8246425032469", is_call_tracking_enabled=True
    )
    assert result.ok
    assert [c[1] for c in client.calls] == ["get_ad_extensions_by_ids", "update_ad_extensions"]
    ext = client.calls[1][2].ad_extensions[0]
    assert ext.id == "8246425032469" and ext.is_call_tracking_enabled is True
    # Phone/country are merged from the fetched extension rather than nulled.
    assert ext.phone_number == "8555665900" and ext.country_code == "US"


def test_update_call_extension_skips_fetch_when_required_fields_supplied() -> None:
    # Both required fields given -> no fetch, single update call.
    client = _ScriptedClient([SimpleNamespace(nested_partial_errors=[])])
    result = extensions.update_call_extension(
        client,
        ad_extension_id="55",
        phone_number="8005550000",
        country_code="US",
        is_call_tracking_enabled=True,
    )
    assert result.ok
    assert [c[1] for c in client.calls] == ["update_ad_extensions"]


def test_update_call_extension_reports_missing_extension() -> None:
    client = _ScriptedClient([SimpleNamespace(ad_extensions=[])])
    result = extensions.update_call_extension(
        client, ad_extension_id="999", is_call_tracking_enabled=True
    )
    assert not result.ok and "not found" in result.message
    # Never attempts the update when the extension can't be read for the merge.
    assert [c[1] for c in client.calls] == ["get_ad_extensions_by_ids"]


def test_add_call_extension_carries_call_tracking_flag() -> None:
    client = _ScriptedClient(
        [
            SimpleNamespace(
                ad_extension_identities=[SimpleNamespace(id="42")], nested_partial_errors=[]
            )
        ]
    )
    result = extensions.add_call_extension(
        client, phone_number="8555665900", country_code="US", is_call_tracking_enabled=True
    )
    assert result.ok and result.ids == ["42"]
    ext = client.calls[0][2].ad_extensions[0]
    assert ext.type == "CallAdExtension" and ext.is_call_tracking_enabled is True


def test_add_call_extension_sets_discriminator_and_associates() -> None:
    client = _ScriptedClient(
        [
            SimpleNamespace(
                ad_extension_identities=[SimpleNamespace(id="42")], nested_partial_errors=[]
            ),
            SimpleNamespace(nested_partial_errors=[]),
        ]
    )
    result = extensions.add_call_extension(
        client, phone_number="2065550100", country_code="US", entity_id="487928625"
    )
    assert result.ok and result.ids == ["42"]
    assert [c[1] for c in client.calls] == ["add_ad_extensions", "set_ad_extensions_associations"]
    ext = client.calls[0][2].ad_extensions[0]
    assert ext.type == "CallAdExtension" and ext.phone_number == "2065550100"


def test_delete_ad_extensions_reports_count() -> None:
    client = _ScriptedClient([SimpleNamespace(partial_errors=[])])
    result = extensions.delete_ad_extensions(client, ad_extension_ids=["8246425030221"])
    assert result.ok and result.ids == ["8246425030221"]
    assert "1 ad extension" in result.message
    _, method, request = client.calls[0]
    assert method == "delete_ad_extensions"
    assert request.ad_extension_ids == ["8246425030221"]


def test_add_callout_creates_then_associates() -> None:
    client = _ScriptedClient(
        [
            SimpleNamespace(
                ad_extension_identities=[SimpleNamespace(id="99")], nested_partial_errors=[]
            ),
            SimpleNamespace(nested_partial_errors=[]),
        ]
    )
    result = extensions.add_callout_extension(client, text="24/7 Support", entity_id="487928625")
    assert result.ok and result.ids == ["99"]
    assert [c[1] for c in client.calls] == [
        "add_ad_extensions",
        "set_ad_extensions_associations",
    ]
    assoc = client.calls[1][2].ad_extension_id_to_entity_id_associations[0]
    assert assoc.ad_extension_id == "99" and assoc.entity_id == "487928625"
