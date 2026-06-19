"""Account-level URL options (CampaignManagementService ``AccountProperties``).

The tracking template, Final URL suffix, and Microsoft Click ID auto-tagging that every campaign
inherits live on the *account*, not on the per-campaign entity. Reading them is how you confirm
click tracking / attribution before activating campaigns whose own template is (normally) blank;
setting them is the single-point way to apply tracking across the whole account at once.
"""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.account_property import AccountProperty
from openapi_client.models.campaign.get_account_properties_request import (
    GetAccountPropertiesRequest,
)
from openapi_client.models.campaign.set_account_properties_request import (
    SetAccountPropertiesRequest,
)

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import AccountUrlOptions, MutationResult
from . import as_list, first_attr, flat_partial_errors

# The URL-tracking subset of account properties we read/write (the rest are billing/bidding/etc.).
_URL_PROPERTY_NAMES = [
    "TrackingUrlTemplate",
    "FinalUrlSuffix",
    "MSCLKIDAutoTaggingEnabled",
    "AdClickParallelTracking",
]


def get_account_url_options(client: MsAdsClient) -> AccountUrlOptions:
    """Read the active account's URL tracking (template, suffix, msclkid auto-tagging)."""
    resp = client.call(
        CAMPAIGN,
        "get_account_properties",
        GetAccountPropertiesRequest(account_property_names=_URL_PROPERTY_NAMES),
    )
    by_name: dict[str, Any] = {}
    for prop in as_list(first_attr(resp, "AccountProperties", "account_properties")):
        name = first_attr(prop, "Name", "name")
        name = getattr(name, "value", name)  # unwrap the AccountPropertyName enum
        if name is not None:
            by_name[str(name)] = first_attr(prop, "Value", "value")
    return AccountUrlOptions.from_properties(by_name)


def set_account_url_options(
    client: MsAdsClient,
    *,
    tracking_url_template: str | None = None,
    final_url_suffix: str | None = None,
    msclkid_auto_tagging_enabled: bool | None = None,
    ad_click_parallel_tracking: bool | None = None,
) -> MutationResult:
    """Set account-level URL options; only the fields you pass change (applies account-wide)."""
    candidates = [
        ("TrackingUrlTemplate", tracking_url_template),
        ("FinalUrlSuffix", final_url_suffix),
        ("MSCLKIDAutoTaggingEnabled", _bool_str(msclkid_auto_tagging_enabled)),
        ("AdClickParallelTracking", _bool_str(ad_click_parallel_tracking)),
    ]
    props = [
        AccountProperty(name=name, value=value) for name, value in candidates if value is not None
    ]
    if not props:
        return MutationResult(ok=False, message="No account URL options provided to update")
    resp = client.call(
        CAMPAIGN,
        "set_account_properties",
        SetAccountPropertiesRequest(account_properties=props),
    )
    errors = flat_partial_errors(resp)
    changed = ", ".join(name for name, value in candidates if value is not None)
    return MutationResult(
        ok=not errors,
        message=f"Account URL options updated ({changed})" if not errors else "Update failed",
        partial_errors=errors,
    )


def _bool_str(value: bool | None) -> str | None:
    """Render an optional bool as Microsoft's "true"/"false" string (None passes through)."""
    if value is None:
        return None
    return "true" if value else "false"
