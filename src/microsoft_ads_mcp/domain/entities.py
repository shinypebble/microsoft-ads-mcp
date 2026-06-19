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
# Location intent: who sees the ad relative to the campaign's targeted locations. Microsoft's
# enum spelling is used verbatim so the value maps straight onto the API. The third historical
# value, "PeopleSearchingForOrViewingPages", was deprecated in April 2024 (Microsoft silently
# coerces it to the default), so it is not offered here -- reads may still return it for legacy
# campaigns since `get_location_intent` returns a plain str, not this Literal.
IntentOption = Literal[
    # People physically in (or regularly in) the targeted locations ("presence").
    "PeopleIn",
    # People in, searching for, or viewing pages about the targeted locations (Microsoft default).
    "PeopleInOrSearchingForOrViewingPages",
]
# Conversion-goal bidding / value knobs. Microsoft's enum spellings, used verbatim so they map
# straight onto the API. (Goal status reuses CampaignStatus -- Active / Paused.)
ConversionCountType = Literal["All", "Unique"]
ConversionRevenueType = Literal["FixedValue", "VariableValue", "NoValue"]
# Days an ad schedule (dayparting) criterion can target. Microsoft's enum spelling is used
# verbatim so it maps straight onto the API.
Weekday = Literal[
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
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


class AccountUrlOptions(BaseModel):
    """Account-level URL tracking: the defaults every campaign inherits unless it overrides them.

    These live on the account (CampaignManagementService ``AccountProperties``), not on the
    per-campaign entity, so a blank ``tracking_url_template`` on a campaign/ad group/ad/keyword is
    normal when it is set here. ``msclkid_auto_tagging_enabled`` is what appends the Microsoft
    Click ID (``msclkid``) used for conversion attribution -- check it before activating campaigns.
    """

    tracking_url_template: str | None = None
    final_url_suffix: str | None = None
    msclkid_auto_tagging_enabled: bool | None = None
    ad_click_parallel_tracking: bool | None = None

    @classmethod
    def from_properties(cls, props: dict[str, Any]) -> AccountUrlOptions:
        """Build from a ``{property name: value}`` map of ``AccountProperty`` rows."""
        return cls(
            tracking_url_template=_blank_to_none(props.get("TrackingUrlTemplate")),
            final_url_suffix=_blank_to_none(props.get("FinalUrlSuffix")),
            msclkid_auto_tagging_enabled=_as_bool(props.get("MSCLKIDAutoTaggingEnabled")),
            ad_click_parallel_tracking=_as_bool(props.get("AdClickParallelTracking")),
        )


class CampaignSummary(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    campaign_type: str | None = None
    daily_budget: float | None = None
    budget_id: str | None = None
    # The campaign time zone (e.g. "CentralTimeUSCanada"). Ad schedules run in this zone unless
    # ad_schedule_use_searcher_time_zone is true, so it's needed to verify a dayparting setup.
    time_zone: str | None = None
    start_date: str | None = None  # "YYYY-MM-DD", or null when the campaign has no explicit start
    languages: list[str] | None = None
    # The bid strategy (BiddingScheme.Type), e.g. "EnhancedCpc", "MaxConversions".
    bid_strategy_type: str | None = None
    # When true, ad-schedule hours are interpreted in each searcher's time zone, not the campaign's.
    # Only populated when get_campaigns requests it; null means "not reported".
    ad_schedule_use_searcher_time_zone: bool | None = None
    # URL tracking (carries the click id + UTMs). null means "not set at this level".
    tracking_url_template: str | None = None
    final_url_suffix: str | None = None
    url_custom_parameters: dict[str, str] | None = None

    @classmethod
    def from_sdk(cls, c: Any) -> CampaignSummary:
        ctype = _get(c, "CampaignType", "campaign_type")
        if isinstance(ctype, list):
            ctype = ", ".join(str(t) for t in ctype) or None
        scheme = _get(c, "BiddingScheme", "bidding_scheme")
        return cls(
            id=str(_get(c, "Id", "id")),
            name=_get(c, "Name", "name"),
            status=_str_or_none(_get(c, "Status", "status")),
            campaign_type=str(ctype) if ctype is not None else None,
            daily_budget=_get(c, "DailyBudget", "daily_budget"),
            budget_id=_str_or_none(_get(c, "BudgetId", "budget_id")),
            time_zone=_get(c, "TimeZone", "time_zone"),
            start_date=_date_str(_get(c, "StartDate", "start_date")),
            languages=_str_list(_get(c, "Languages", "languages")),
            bid_strategy_type=(
                _str_or_none(_get(scheme, "Type", "type")) if scheme is not None else None
            ),
            ad_schedule_use_searcher_time_zone=_get(
                c, "AdScheduleUseSearcherTimeZone", "ad_schedule_use_searcher_time_zone"
            ),
            tracking_url_template=_get(c, "TrackingUrlTemplate", "tracking_url_template"),
            final_url_suffix=_get(c, "FinalUrlSuffix", "final_url_suffix"),
            url_custom_parameters=_custom_params(c),
        )


class AdGroupSummary(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    cpc_bid: float | None = None
    # URL tracking. null means "not set here" (the campaign-level value, if any, applies).
    tracking_url_template: str | None = None
    final_url_suffix: str | None = None
    url_custom_parameters: dict[str, str] | None = None

    @classmethod
    def from_sdk(cls, ag: Any) -> AdGroupSummary:
        bid = _get(ag, "CpcBid", "cpc_bid")
        amount = _get(bid, "Amount", "amount") if bid is not None else None
        return cls(
            id=str(_get(ag, "Id", "id")),
            name=_get(ag, "Name", "name"),
            status=_str_or_none(_get(ag, "Status", "status")),
            cpc_bid=amount,
            tracking_url_template=_get(ag, "TrackingUrlTemplate", "tracking_url_template"),
            final_url_suffix=_get(ag, "FinalUrlSuffix", "final_url_suffix"),
            url_custom_parameters=_custom_params(ag),
        )


class KeywordSummary(BaseModel):
    id: str
    text: str | None = None
    match_type: str | None = None
    status: str | None = None
    bid: float | None = None
    # Keyword-level URL overrides (take precedence over ad-group/campaign values when set).
    final_url: str | None = None
    tracking_url_template: str | None = None
    final_url_suffix: str | None = None
    url_custom_parameters: dict[str, str] | None = None

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
            final_url=_first_final_url(kw),
            tracking_url_template=_get(kw, "TrackingUrlTemplate", "tracking_url_template"),
            final_url_suffix=_get(kw, "FinalUrlSuffix", "final_url_suffix"),
            url_custom_parameters=_custom_params(kw),
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
    # URL tracking on the ad itself.
    tracking_url_template: str | None = None
    final_url_suffix: str | None = None
    url_custom_parameters: dict[str, str] | None = None

    @classmethod
    def from_sdk(cls, ad: Any) -> AdSummary:
        return cls(
            id=str(_get(ad, "Id", "id")),
            ad_type=_str_or_none(_get(ad, "Type", "type")),
            status=_str_or_none(_get(ad, "Status", "status")),
            final_url=_first_final_url(ad),
            headlines=_asset_texts(_get(ad, "Headlines", "headlines")),
            descriptions=_asset_texts(_get(ad, "Descriptions", "descriptions")),
            path1=_get(ad, "Path1", "path1"),
            path2=_get(ad, "Path2", "path2"),
            tracking_url_template=_get(ad, "TrackingUrlTemplate", "tracking_url_template"),
            final_url_suffix=_get(ad, "FinalUrlSuffix", "final_url_suffix"),
            url_custom_parameters=_custom_params(ad),
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
    # Whether Microsoft call tracking is on (the number shown is a forwarding number, so call
    # conversions are measured). null for non-call extensions.
    is_call_tracking_enabled: bool | None = None
    # Callout / structured snippet
    text: str | None = None
    # Sitelink
    display_text: str | None = None
    final_url: str | None = None

    @classmethod
    def from_sdk(cls, ext: Any) -> AdExtensionSummary:
        return cls(
            id=str(_get(ext, "Id", "id")),
            ad_extension_type=_str_or_none(_get(ext, "Type", "type")),
            status=_str_or_none(_get(ext, "Status", "status")),
            phone_number=_get(ext, "PhoneNumber", "phone_number"),
            country_code=_get(ext, "CountryCode", "country_code"),
            is_call_tracking_enabled=_get(ext, "IsCallTrackingEnabled", "is_call_tracking_enabled"),
            text=_get(ext, "Text", "text"),
            display_text=_get(ext, "DisplayText", "display_text"),
            final_url=_first_final_url(ext),
        )


class ConversionGoalSummary(BaseModel):
    id: str
    name: str | None = None
    goal_type: str | None = None
    status: str | None = None
    tag_id: str | None = None
    tracking_status: str | None = None
    # The inverse of the UI's "Include in conversions" checkbox: the single switch for whether
    # the goal steers automated bidding. False => counts in the Conversions column and ECPC/tCPA
    # bid math; True => only reported under All conversions, ignored by bidding.
    exclude_from_bidding: bool | None = None
    count_type: str | None = None  # "All" (every conversion per click) or "Unique" (one per click)
    conversion_window_in_minutes: int | None = None  # click-to-conversion lookback
    goal_category: str | None = None  # e.g. Purchase, SubmitLeadForm, Signup, None
    # Conversion value model, flattened from the SDK's nested Revenue object.
    revenue_type: str | None = None  # "FixedValue" / "VariableValue" / "NoValue"
    revenue_value: float | None = None
    revenue_currency_code: str | None = None

    @classmethod
    def from_sdk(cls, g: Any) -> ConversionGoalSummary:
        revenue = _get(g, "Revenue", "revenue")
        return cls(
            id=str(_get(g, "Id", "id")),
            name=_get(g, "Name", "name"),
            goal_type=_str_or_none(_get(g, "Type", "type")),
            status=_str_or_none(_get(g, "Status", "status")),
            tag_id=_str_or_none(_get(g, "TagId", "tag_id")),
            tracking_status=_str_or_none(_get(g, "TrackingStatus", "tracking_status")),
            exclude_from_bidding=_get(g, "ExcludeFromBidding", "exclude_from_bidding"),
            count_type=_str_or_none(_get(g, "CountType", "count_type")),
            conversion_window_in_minutes=_get(
                g, "ConversionWindowInMinutes", "conversion_window_in_minutes"
            ),
            goal_category=_str_or_none(_get(g, "GoalCategory", "goal_category")),
            revenue_type=_str_or_none(_get(revenue, "Type", "type")) if revenue else None,
            revenue_value=_get(revenue, "Value", "value") if revenue else None,
            revenue_currency_code=(
                _get(revenue, "CurrencyCode", "currency_code") if revenue else None
            ),
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
            # Location bid adjustments are BidMultiplier (Multiplier); other bids use Amount.
            bid_adjustment=(
                _get(bid, "Multiplier", "multiplier", "Amount", "amount") if bid else None
            ),
        )


class LocationIntentSummary(BaseModel):
    """The single location-intent criterion on a campaign (presence vs. search interest)."""

    criterion_id: str | None = None  # the campaign criterion id (equals the campaign id)
    campaign_id: str | None = None
    intent_option: str | None = None

    @classmethod
    def from_sdk(cls, c: Any) -> LocationIntentSummary:
        crit = _get(c, "Criterion", "criterion")
        return cls(
            criterion_id=_str_or_none(_get(c, "Id", "id")),
            campaign_id=_str_or_none(_get(c, "CampaignId", "campaign_id")),
            intent_option=(
                _str_or_none(_get(crit, "IntentOption", "intent_option")) if crit else None
            ),
        )


class DeviceBidAdjustmentSummary(BaseModel):
    """A device bid-adjustment criterion on a campaign (one per device type).

    A campaign normally has either no device criterions (no modifier on any device) or all three
    (Computers / Smartphones / Tablets). ``bid_adjustment`` is a percent modifier; -100 excludes
    the device entirely.
    """

    criterion_id: str | None = None  # the campaign criterion id
    campaign_id: str | None = None
    device: str | None = None  # "Computers", "Smartphones", or "Tablets"
    bid_adjustment: float | None = None

    @classmethod
    def from_sdk(cls, c: Any) -> DeviceBidAdjustmentSummary:
        crit = _get(c, "Criterion", "criterion")
        bid = _get(c, "CriterionBid", "criterion_bid")
        return cls(
            criterion_id=_str_or_none(_get(c, "Id", "id")),
            campaign_id=_str_or_none(_get(c, "CampaignId", "campaign_id")),
            device=_get(crit, "DeviceName", "device_name") if crit else None,
            # Device bid adjustments are BidMultiplier (Multiplier), like location/ad-schedule.
            bid_adjustment=(
                _get(bid, "Multiplier", "multiplier", "Amount", "amount") if bid else None
            ),
        )


class AdScheduleInput(BaseModel):
    """One dayparting window to add to a campaign.

    Hours are 0-24 (``from_hour`` inclusive, ``to_hour`` exclusive of the final minutes); minutes
    are at 15-minute granularity, so only 0/15/30/45 are accepted. Times run in the campaign's
    time zone unless ``use_searcher_time_zone`` is set on the campaign.
    """

    day: Weekday
    from_hour: int  # 0-24
    to_hour: int  # 0-24
    from_minute: int = 0  # 0, 15, 30, or 45
    to_minute: int = 0  # 0, 15, 30, or 45
    bid_adjustment: float = 0.0  # percent modifier applied during this window (0 = no change)


class AdScheduleSummary(BaseModel):
    """One ad-schedule (dayparting) criterion on a campaign."""

    criterion_id: str | None = None  # the campaign criterion id (use this to remove the window)
    campaign_id: str | None = None
    day: str | None = None
    from_hour: int | None = None
    from_minute: int | None = None
    to_hour: int | None = None
    to_minute: int | None = None
    bid_adjustment: float | None = None

    @classmethod
    def from_sdk(cls, c: Any) -> AdScheduleSummary:
        crit = _get(c, "Criterion", "criterion")
        bid = _get(c, "CriterionBid", "criterion_bid")
        return cls(
            criterion_id=_str_or_none(_get(c, "Id", "id")),
            campaign_id=_str_or_none(_get(c, "CampaignId", "campaign_id")),
            day=_str_or_none(_get(crit, "Day", "day")) if crit else None,
            from_hour=_get(crit, "FromHour", "from_hour") if crit else None,
            from_minute=_minute_to_int(_get(crit, "FromMinute", "from_minute")) if crit else None,
            to_hour=_get(crit, "ToHour", "to_hour") if crit else None,
            to_minute=_minute_to_int(_get(crit, "ToMinute", "to_minute")) if crit else None,
            bid_adjustment=(
                _get(bid, "Multiplier", "multiplier", "Amount", "amount") if bid else None
            ),
        )


class AdScheduleSettings(BaseModel):
    """A campaign's full ad-schedule view: the windows plus the time-zone context they run in."""

    campaign_id: str
    time_zone: str | None = None
    use_searcher_time_zone: bool | None = None
    schedules: list[AdScheduleSummary] = []


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


def _blank_to_none(val: Any) -> str | None:
    """Stringify, treating an empty string (Microsoft's "unset") as None."""
    if val is None:
        return None
    return str(val) or None


def _as_bool(val: Any) -> bool | None:
    """Parse a Microsoft account-property boolean ("true"/"false" string) to a bool, else None."""
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("true", "1"):
        return True
    if s in ("false", "0"):
        return False
    return None


_MINUTE_NAME_TO_INT = {"Zero": 0, "Fifteen": 15, "Thirty": 30, "FortyFive": 45}


def _minute_to_int(val: Any) -> int | None:
    """Map a Microsoft ``Minute`` enum (Zero/Fifteen/Thirty/FortyFive) to its integer minute."""
    if val is None:
        return None
    name = str(getattr(val, "value", val))
    return _MINUTE_NAME_TO_INT.get(name)


def _date_str(val: Any) -> str | None:
    """Render an SDK date (``datetime`` or a ``{Year, Month, Day}`` object) as "YYYY-MM-DD"."""
    if val is None:
        return None
    year = _get(val, "Year", "year")
    month = _get(val, "Month", "month")
    day = _get(val, "Day", "day")
    if year and month and day:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    # A bare datetime: take the date portion of its ISO form.
    iso = getattr(val, "isoformat", None)
    return iso()[:10] if callable(iso) else str(val)


def _str_list(val: Any) -> list[str] | None:
    """Normalize a string-list field (bare list or ``{"string": [...]}`` wrapper) to a list."""
    if val is None:
        return None
    items = _get(val, "string", default=val)
    if isinstance(items, list):
        return [str(i) for i in items] or None
    return None


def _first_final_url(obj: Any) -> str | None:
    """Return the first ``FinalUrls`` entry (the landing page), or None.

    Tolerates the bare list the REST SDK returns or a ``{"string": [...]}`` wrapper.
    """
    urls = _get(obj, "FinalUrls", "final_urls")
    if urls is None:
        return None
    items = _get(urls, "string", default=urls)
    if isinstance(items, list) and items:
        return str(items[0])
    return None


def _custom_params(obj: Any) -> dict[str, str] | None:
    """Flatten ``UrlCustomParameters`` (a list of Key/Value pairs) into a plain dict.

    These are the ``{_key}`` substitutions a tracking template / Final URL suffix can reference.
    Returns None when none are set, so the field stays absent rather than an empty object.
    """
    cp = _get(obj, "UrlCustomParameters", "url_custom_parameters")
    if cp is None:
        return None
    params = _get(cp, "Parameters", "parameters")
    items = (
        params
        if isinstance(params, list)
        else _get(params, "CustomParameter", "custom_parameter", default=[])
    )
    out: dict[str, str] = {}
    for p in items if isinstance(items, list) else []:
        key = _get(p, "Key", "key")
        if key is not None:
            val = _get(p, "Value", "value")
            out[str(key)] = str(val) if val is not None else ""
    return out or None


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
