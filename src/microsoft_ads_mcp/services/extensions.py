"""Ad-extension flows: list extensions, update a call extension, add callout/sitelink.

Extensions are account-level objects that get *associated* to a campaign or ad group. Adding a
new extension is therefore two steps: create it (``add_ad_extensions``) then associate it
(``set_ad_extensions_associations``). Updating an existing one (e.g. a call extension's phone
number) is a single in-place ``update_ad_extensions`` and needs no re-association.
"""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.ad_extension_id_to_entity_id_association import (
    AdExtensionIdToEntityIdAssociation,
)
from openapi_client.models.campaign.ad_extensions_type_filter import AdExtensionsTypeFilter
from openapi_client.models.campaign.add_ad_extensions_request import AddAdExtensionsRequest
from openapi_client.models.campaign.call_ad_extension import CallAdExtension
from openapi_client.models.campaign.callout_ad_extension import CalloutAdExtension
from openapi_client.models.campaign.delete_ad_extensions_request import DeleteAdExtensionsRequest
from openapi_client.models.campaign.get_ad_extension_ids_by_account_id_request import (
    GetAdExtensionIdsByAccountIdRequest,
)
from openapi_client.models.campaign.get_ad_extensions_by_ids_request import (
    GetAdExtensionsByIdsRequest,
)
from openapi_client.models.campaign.set_ad_extensions_associations_request import (
    SetAdExtensionsAssociationsRequest,
)
from openapi_client.models.campaign.sitelink_ad_extension import SitelinkAdExtension
from openapi_client.models.campaign.update_ad_extensions_request import UpdateAdExtensionsRequest

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import AdExtensionSummary, MutationResult
from . import as_list, first_attr, flat_partial_errors, nested_partial_errors

# Association scopes: which entity an extension is attached to.
_ASSOCIATION_TYPES = ("Account", "Campaign", "AdGroup")

# Default get-filter: the common, broadly-supported extension types. The full OR of every
# member is rejected (400) by the get endpoints, so we use a curated set when none is given.
_DEFAULT_TYPE_NAMES = (
    "CALLADEXTENSION",
    "CALLOUTADEXTENSION",
    "SITELINKADEXTENSION",
    "STRUCTUREDSNIPPETADEXTENSION",
    "IMAGEADEXTENSION",
    "PRICEADEXTENSION",
    "PROMOTIONADEXTENSION",
    "LOCATIONADEXTENSION",
    "ACTIONADEXTENSION",
)


def _default_types() -> AdExtensionsTypeFilter:
    """A curated set of common extension types the get-calls accept (full OR is rejected)."""
    result: AdExtensionsTypeFilter | None = None
    for name in _DEFAULT_TYPE_NAMES:
        member = AdExtensionsTypeFilter[name]
        result = member if result is None else result | member
    assert result is not None
    return result


def _type_filter(extension_types: list[str] | None) -> AdExtensionsTypeFilter:
    """Resolve friendly type names (e.g. "Call", "Sitelink") to a combined flag.

    Names match case-insensitively, with or without the trailing "AdExtension"; ``None``
    returns the curated default set.
    """
    if not extension_types:
        return _default_types()

    def norm(s: str) -> str:
        return s.upper().replace("ADEXTENSION", "").replace("_", "").replace(" ", "")

    result: AdExtensionsTypeFilter | None = None
    for name in extension_types:
        target = norm(name)
        member = next(
            (m for m in AdExtensionsTypeFilter if m.name != "NONE" and norm(m.name) == target),
            None,
        )
        if member is None:
            raise ValueError(f"unknown ad extension type {name!r}")
        result = member if result is None else result | member
    return result if result is not None else _default_types()


def _check_association(association_type: str) -> None:
    if association_type not in _ASSOCIATION_TYPES:
        raise ValueError(f"association_type must be one of {', '.join(_ASSOCIATION_TYPES)}")


def get_ad_extensions(
    client: MsAdsClient,
    *,
    extension_types: list[str] | None = None,
    association_type: str = "Account",
) -> list[AdExtensionSummary]:
    """List ad extensions in the account, optionally filtered by type."""
    _check_association(association_type)
    type_filter = _type_filter(extension_types)
    ids_resp = client.call(
        CAMPAIGN,
        "get_ad_extension_ids_by_account_id",
        GetAdExtensionIdsByAccountIdRequest(
            account_id=client.account_id,
            association_type=association_type,
            ad_extension_type=type_filter,
        ),
    )
    ext_ids = [str(i) for i in as_list(first_attr(ids_resp, "AdExtensionIds", "ad_extension_ids"))]
    if not ext_ids:
        return []
    resp = client.call(
        CAMPAIGN,
        "get_ad_extensions_by_ids",
        GetAdExtensionsByIdsRequest(
            account_id=client.account_id, ad_extension_ids=ext_ids, ad_extension_type=type_filter
        ),
    )
    items = as_list(first_attr(resp, "AdExtensions", "ad_extensions"))
    return [AdExtensionSummary.from_sdk(e) for e in items if e is not None]


def _get_call_extension(client: MsAdsClient, ad_extension_id: str) -> Any:
    """Fetch a single call extension by id (or None) so an update can merge required fields."""
    resp = client.call(
        CAMPAIGN,
        "get_ad_extensions_by_ids",
        GetAdExtensionsByIdsRequest(
            account_id=client.account_id,
            ad_extension_ids=[ad_extension_id],
            ad_extension_type=_type_filter(["Call"]),
        ),
    )
    items = as_list(first_attr(resp, "AdExtensions", "ad_extensions"))
    return next((e for e in items if e is not None), None)


def update_call_extension(
    client: MsAdsClient,
    *,
    ad_extension_id: str,
    phone_number: str | None = None,
    country_code: str | None = None,
    is_call_only: bool | None = None,
    is_call_tracking_enabled: bool | None = None,
) -> MutationResult:
    """Update an existing call extension in place (e.g. the brand's phone number or call tracking).

    Microsoft's update *replaces* the whole CallAdExtension, so it requires the phone number and
    country code on every update -- omitting them would null them (and the API rejects that).
    To honor the "only the fields you pass change" contract for single-field toggles (e.g. just
    flipping ``is_call_tracking_enabled``), we fetch the current extension and re-send the existing
    ``phone_number`` / ``country_code`` whenever the caller leaves them out.
    """
    if phone_number is None or country_code is None:
        existing = _get_call_extension(client, ad_extension_id)
        if existing is None:
            return MutationResult(
                ok=False,
                message=f"Call extension {ad_extension_id} not found",
                ids=[],
                partial_errors=[f"Call extension {ad_extension_id} not found"],
            )
        if phone_number is None:
            phone_number = first_attr(existing, "PhoneNumber", "phone_number")
        if country_code is None:
            country_code = first_attr(existing, "CountryCode", "country_code")

    fields: dict[str, Any] = {}
    if phone_number is not None:
        fields["phone_number"] = phone_number
    if country_code is not None:
        fields["country_code"] = country_code
    if is_call_only is not None:
        fields["is_call_only"] = is_call_only
    if is_call_tracking_enabled is not None:
        fields["is_call_tracking_enabled"] = is_call_tracking_enabled
    ext = CallAdExtension(id=ad_extension_id, type="CallAdExtension", **fields)
    resp = client.call(
        CAMPAIGN,
        "update_ad_extensions",
        UpdateAdExtensionsRequest(account_id=client.account_id, ad_extensions=[ext]),
    )
    errors = nested_partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"Call extension {ad_extension_id} updated" if not errors else "Update failed",
        ids=[str(ad_extension_id)],
        partial_errors=errors,
    )


def _add_and_associate(
    client: MsAdsClient, ext: Any, entity_id: str | None, association_type: str, label: str
) -> MutationResult:
    """Create an extension, then (optionally) associate it to a campaign/ad group."""
    resp = client.call(
        CAMPAIGN,
        "add_ad_extensions",
        AddAdExtensionsRequest(account_id=client.account_id, ad_extensions=[ext]),
    )
    errors = nested_partial_errors(resp)
    identities = as_list(first_attr(resp, "AdExtensionIdentities", "ad_extension_identities"))
    ids = [str(first_attr(i, "Id", "id")) for i in identities if first_attr(i, "Id", "id")]
    if errors or not ids:
        return MutationResult(
            ok=False, message=f"{label} create failed", ids=ids, partial_errors=errors
        )
    if entity_id is not None:
        _check_association(association_type)
        assoc = AdExtensionIdToEntityIdAssociation(ad_extension_id=ids[0], entity_id=entity_id)
        assoc_resp = client.call(
            CAMPAIGN,
            "set_ad_extensions_associations",
            SetAdExtensionsAssociationsRequest(
                account_id=client.account_id,
                ad_extension_id_to_entity_id_associations=[assoc],
                association_type=association_type,
            ),
        )
        assoc_errors = nested_partial_errors(assoc_resp)
        if assoc_errors:
            return MutationResult(
                ok=False,
                message=f"{label} created (id {ids[0]}) but association failed",
                ids=ids,
                partial_errors=assoc_errors,
            )
    where = f" and associated to {association_type.lower()} {entity_id}" if entity_id else ""
    return MutationResult(ok=True, message=f"{label} created (id {ids[0]}){where}", ids=ids)


def add_callout_extension(
    client: MsAdsClient,
    *,
    text: str,
    entity_id: str | None = None,
    association_type: str = "Campaign",
) -> MutationResult:
    """Create a callout extension and optionally associate it to a campaign or ad group."""
    ext = CalloutAdExtension(type="CalloutAdExtension", text=text[:25])
    return _add_and_associate(client, ext, entity_id, association_type, "Callout extension")


def add_sitelink_extension(
    client: MsAdsClient,
    *,
    display_text: str,
    final_url: str,
    entity_id: str | None = None,
    association_type: str = "Campaign",
) -> MutationResult:
    """Create a sitelink extension and optionally associate it to a campaign or ad group."""
    ext = SitelinkAdExtension(
        type="SitelinkAdExtension", display_text=display_text[:25], final_urls=[final_url]
    )
    return _add_and_associate(client, ext, entity_id, association_type, "Sitelink extension")


def add_call_extension(
    client: MsAdsClient,
    *,
    phone_number: str,
    country_code: str = "US",
    is_call_only: bool = False,
    is_call_tracking_enabled: bool = False,
    entity_id: str | None = None,
    association_type: str = "Campaign",
) -> MutationResult:
    """Create a call extension and optionally associate it to a campaign or ad group.

    ``is_call_tracking_enabled`` turns on Microsoft call tracking (US/UK only): Microsoft swaps
    the displayed number for a forwarding number so call conversions can be measured. Note new
    toll-free forwarding numbers are no longer provisioned (since Aug 2017), so tracking yields a
    *local* forwarding number.
    """
    ext = CallAdExtension(
        type="CallAdExtension",
        phone_number=phone_number,
        country_code=country_code,
        is_call_only=is_call_only,
        is_call_tracking_enabled=is_call_tracking_enabled,
    )
    return _add_and_associate(client, ext, entity_id, association_type, "Call extension")


def delete_ad_extensions(client: MsAdsClient, *, ad_extension_ids: list[str]) -> MutationResult:
    """Delete account-level ad extensions by id (removes the objects, not just associations)."""
    resp = client.call(
        CAMPAIGN,
        "delete_ad_extensions",
        DeleteAdExtensionsRequest(account_id=client.account_id, ad_extension_ids=ad_extension_ids),
    )
    errors = flat_partial_errors(resp)
    n = len(ad_extension_ids)
    return MutationResult(
        ok=not errors,
        message=(
            f"Deleted {n} ad extension{'s' if n != 1 else ''}"
            if not errors
            else "Delete ad extensions failed"
        ),
        ids=[str(i) for i in ad_extension_ids],
        partial_errors=errors,
    )
