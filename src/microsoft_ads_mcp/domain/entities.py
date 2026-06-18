"""Compact, agent-facing models for tool outputs.

These are *our* summaries, not the SDK's wire models (``openapi_client.models.*``). The SDK
models carry dozens of fields; tools return these trimmed views so the agent sees the
high-signal fields and stable shapes. Conversion from SDK objects happens in the services
layer via ``from_sdk`` helpers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# The match types and statuses we accept/return, kept as Literals for agent clarity.
MatchType = Literal["Broad", "Phrase", "Exact"]
CampaignStatus = Literal["Active", "Paused"]
# Negative keywords attach to either a campaign or an ad group (no reusable list object here).
NegativeEntityType = Literal["Campaign", "AdGroup"]
# Discriminated auth result so a client can branch deterministically instead of string-matching.
AuthState = Literal[
    "ok",
    "no_token",
    "token_expired",
    "token_rejected",
    "dev_token_missing",
    "account_inactive",
]


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first present attribute (msads models expose Pascal and snake_case)."""
    for name in names:
        val = getattr(obj, name, None)
        if val is not None:
            return val
    return default


class AccountHealth(BaseModel):
    """Result of the first call an agent should make: validates auth and reports mode.

    ``auth_state`` lets a client branch deterministically (e.g. only prompt interactive sign-in
    when ``needs_interactive_auth`` is true) instead of pattern-matching the error ``message``.
    """

    ok: bool
    auth_state: AuthState = "ok"
    needs_interactive_auth: bool = False
    read_only: bool
    environment: str
    message: str
    user_name: str | None = None
    account_id: str | None = None
    customer_id: str | None = None


class AccountSummary(BaseModel):
    id: str
    name: str | None = None
    number: str | None = None
    customer_id: str | None = None
    status: str | None = None

    @classmethod
    def from_sdk(cls, acc: Any, customer_id: Any = None) -> AccountSummary:
        return cls(
            id=str(_get(acc, "Id", "id")),
            name=_get(acc, "Name", "name"),
            number=_get(acc, "Number", "number"),
            customer_id=str(customer_id) if customer_id is not None else None,
            status=_get(acc, "AccountLifeCycleStatus", "account_life_cycle_status"),
        )


class CampaignSummary(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    campaign_type: str | None = None
    daily_budget: float | None = None
    budget_id: str | None = None

    @classmethod
    def from_sdk(cls, c: Any) -> CampaignSummary:
        ctype = _get(c, "CampaignType", "campaign_type")
        if isinstance(ctype, list):
            ctype = ", ".join(str(t) for t in ctype) or None
        return cls(
            id=str(_get(c, "Id", "id")),
            name=_get(c, "Name", "name"),
            status=_str_or_none(_get(c, "Status", "status")),
            campaign_type=str(ctype) if ctype is not None else None,
            daily_budget=_get(c, "DailyBudget", "daily_budget"),
            budget_id=_str_or_none(_get(c, "BudgetId", "budget_id")),
        )


class AdGroupSummary(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    cpc_bid: float | None = None

    @classmethod
    def from_sdk(cls, ag: Any) -> AdGroupSummary:
        bid = _get(ag, "CpcBid", "cpc_bid")
        amount = _get(bid, "Amount", "amount") if bid is not None else None
        return cls(
            id=str(_get(ag, "Id", "id")),
            name=_get(ag, "Name", "name"),
            status=_str_or_none(_get(ag, "Status", "status")),
            cpc_bid=amount,
        )


class KeywordSummary(BaseModel):
    id: str
    text: str | None = None
    match_type: str | None = None
    status: str | None = None
    bid: float | None = None

    @classmethod
    def from_sdk(cls, kw: Any) -> KeywordSummary:
        bid = _get(kw, "Bid", "bid")
        amount = _get(bid, "Amount", "amount") if bid is not None else None
        return cls(
            id=str(_get(kw, "Id", "id")),
            text=_get(kw, "Text", "text"),
            match_type=_str_or_none(_get(kw, "MatchType", "match_type")),
            status=_str_or_none(_get(kw, "Status", "status")),
            bid=amount,
        )


class AdSummary(BaseModel):
    id: str
    ad_type: str | None = None
    status: str | None = None
    final_url: str | None = None
    # RSA copy, so an agent can show or clone an ad (e.g. recreate under a new brand/URL).
    headlines: list[str] = []
    descriptions: list[str] = []
    path1: str | None = None
    path2: str | None = None

    @classmethod
    def from_sdk(cls, ad: Any) -> AdSummary:
        urls = _get(ad, "FinalUrls", "final_urls")
        final_url = None
        if urls is not None:
            items = _get(urls, "string", default=urls)
            if isinstance(items, list) and items:
                final_url = str(items[0])
        return cls(
            id=str(_get(ad, "Id", "id")),
            ad_type=_str_or_none(_get(ad, "Type", "type")),
            status=_str_or_none(_get(ad, "Status", "status")),
            final_url=final_url,
            headlines=_asset_texts(_get(ad, "Headlines", "headlines")),
            descriptions=_asset_texts(_get(ad, "Descriptions", "descriptions")),
            path1=_get(ad, "Path1", "path1"),
            path2=_get(ad, "Path2", "path2"),
        )


class NegativeKeywordSummary(BaseModel):
    id: str | None = None
    text: str | None = None
    match_type: str | None = None
    entity_id: str | None = None
    entity_type: str | None = None

    @classmethod
    def from_sdk(
        cls, nk: Any, entity_id: Any = None, entity_type: str | None = None
    ) -> NegativeKeywordSummary:
        return cls(
            id=_str_or_none(_get(nk, "Id", "id")),
            text=_get(nk, "Text", "text"),
            match_type=_str_or_none(_get(nk, "MatchType", "match_type")),
            entity_id=str(entity_id) if entity_id is not None else None,
            entity_type=entity_type,
        )


class AdExtensionSummary(BaseModel):
    """Compact, type-spanning view of an ad extension (call, callout, sitelink, ...)."""

    id: str
    ad_extension_type: str | None = None
    status: str | None = None
    # Call extension
    phone_number: str | None = None
    country_code: str | None = None
    # Callout / structured snippet
    text: str | None = None
    # Sitelink
    display_text: str | None = None
    final_url: str | None = None

    @classmethod
    def from_sdk(cls, ext: Any) -> AdExtensionSummary:
        urls = _get(ext, "FinalUrls", "final_urls")
        final_url = None
        if urls is not None:
            items = _get(urls, "string", default=urls)
            if isinstance(items, list) and items:
                final_url = str(items[0])
        return cls(
            id=str(_get(ext, "Id", "id")),
            ad_extension_type=_str_or_none(_get(ext, "Type", "type")),
            status=_str_or_none(_get(ext, "Status", "status")),
            phone_number=_get(ext, "PhoneNumber", "phone_number"),
            country_code=_get(ext, "CountryCode", "country_code"),
            text=_get(ext, "Text", "text"),
            display_text=_get(ext, "DisplayText", "display_text"),
            final_url=final_url,
        )


class ConversionGoalSummary(BaseModel):
    id: str
    name: str | None = None
    goal_type: str | None = None
    status: str | None = None
    tag_id: str | None = None
    tracking_status: str | None = None

    @classmethod
    def from_sdk(cls, g: Any) -> ConversionGoalSummary:
        return cls(
            id=str(_get(g, "Id", "id")),
            name=_get(g, "Name", "name"),
            goal_type=_str_or_none(_get(g, "Type", "type")),
            status=_str_or_none(_get(g, "Status", "status")),
            tag_id=_str_or_none(_get(g, "TagId", "tag_id")),
            tracking_status=_str_or_none(_get(g, "TrackingStatus", "tracking_status")),
        )


class UetTagSummary(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    tracking_status: str | None = None

    @classmethod
    def from_sdk(cls, t: Any) -> UetTagSummary:
        return cls(
            id=str(_get(t, "Id", "id")),
            name=_get(t, "Name", "name"),
            description=_get(t, "Description", "description"),
            tracking_status=_str_or_none(_get(t, "TrackingStatus", "tracking_status")),
        )


class LocationCriterionSummary(BaseModel):
    """A location target/exclusion attached to a campaign."""

    id: str | None = None  # the campaign criterion id (use this to remove the target)
    campaign_id: str | None = None
    location_id: str | None = None
    location_type: str | None = None
    display_name: str | None = None
    is_excluded: bool = False
    bid_adjustment: float | None = None

    @classmethod
    def from_sdk(cls, c: Any) -> LocationCriterionSummary:
        crit = _get(c, "Criterion", "criterion")
        bid = _get(c, "CriterionBid", "criterion_bid")
        ctype = _str_or_none(_get(c, "Type", "type")) or ""
        return cls(
            id=_str_or_none(_get(c, "Id", "id")),
            campaign_id=_str_or_none(_get(c, "CampaignId", "campaign_id")),
            location_id=_str_or_none(_get(crit, "LocationId", "location_id")) if crit else None,
            location_type=_get(crit, "LocationType", "location_type") if crit else None,
            display_name=_get(crit, "DisplayName", "display_name") if crit else None,
            is_excluded="Negative" in ctype,
            bid_adjustment=_get(bid, "Amount", "amount") if bid else None,
        )


class PostalCodeLocation(BaseModel):
    """Result of resolving a ZIP/postal code to a Microsoft LocationId."""

    postal_code: str
    location_id: str | None = None
    found: bool = False


class MutationResult(BaseModel):
    """Generic result for create/update tools."""

    ok: bool
    message: str
    ids: list[str] = []
    partial_errors: list[str] = []


class ReportRow(BaseModel):
    """One row of a downloaded performance report, as column -> value strings."""

    values: dict[str, str]


class ReportResult(BaseModel):
    """A completed performance report: its columns and parsed rows."""

    report_type: str
    date_range: str
    columns: list[str]
    row_count: int
    rows: list[ReportRow]


def _str_or_none(val: Any) -> str | None:
    """Stringify a value, unwrapping SDK enums to ``.value`` (not the ``Class.MEMBER`` repr)."""
    if val is None:
        return None
    return str(getattr(val, "value", val))


def _asset_texts(links: Any) -> list[str]:
    """Pull the text out of a list of ``AssetLink`` (an RSA's headlines or descriptions).

    Inverse of the services layer's ``_asset_link``: each link wraps a ``TextAsset`` whose
    ``Text`` carries the copy. Tolerates the bare list the REST SDK returns or a typed wrapper.
    """
    if links is None:
        return []
    items = links if isinstance(links, list) else _get(links, "AssetLink", "asset_link", default=[])
    out: list[str] = []
    for link in items if isinstance(items, list) else []:
        asset = _get(link, "Asset", "asset")
        text = _get(asset, "Text", "text") if asset is not None else None
        if text is not None:
            out.append(str(text))
    return out
