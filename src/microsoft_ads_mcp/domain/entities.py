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
# Ad distribution (the ad group's Network / "Ad distribution" setting): which Microsoft search
# surfaces the ad group serves on. These are the two choices Microsoft's UI offers for Search ad
# groups; spellings are used verbatim so they map straight onto the API. The SDK enum carries two
# more values we deliberately do NOT offer for writes: "SyndicatedSearchOnly" -- Microsoft
# consolidated it away and rejects it for Search ad groups (CampaignServiceInvalidNetwork, confirmed
# live) -- and "InHousePromotion", an in-house-promotion mode that isn't advertiser ad distribution.
# Reads may still return any of these since `get_ad_groups` returns a plain str, not this Literal.
Network = Literal[
    # "The entire Microsoft Advertising Network": Microsoft owned-and-operated sites PLUS all
    # syndicated search partners (Microsoft's default).
    "OwnedAndOperatedAndSyndicatedSearch",
    # "Microsoft sites and select traffic": Microsoft sites plus a quality-screened partner subset
    # (still some partner traffic, not pure owned-and-operated).
    "OwnedAndOperatedOnly",
]
# A campaign's inline (campaign-level) bid strategy -- the BiddingScheme.Type. These are the
# settable schemes Microsoft's UI offers for Search campaigns; spellings are the SDK
# `BiddingScheme.Type` discriminator names used verbatim. Note a read/write quirk: for TargetRoas
# and MaxConversionValue the discriminator the API *returns* is the long class-name form
# ("TargetRoasBiddingScheme" / "MaxConversionValueBiddingScheme"), so `get_campaigns` reports those
# long forms -- the write path accepts either form (it normalizes the trailing "BiddingScheme"), so
# a value read back can be passed straight to update_campaign. Distinct from a *portfolio* strategy
# applied by `bid_strategy_id`; you set one or the other, not both.
BidStrategyType = Literal[
    "EnhancedCpc",
    "ManualCpc",
    "MaxClicks",
    "MaxConversions",
    "TargetCpa",
    "MaxConversionValue",
    "TargetRoas",
]
# The set the *write* tools accept: the settable short forms above plus the two long class-name
# discriminators the API hands back for them (the read/write quirk noted above). `get_campaigns`
# reports "TargetRoasBiddingScheme" / "MaxConversionValueBiddingScheme" for those strategies, and
# the write path normalizes either form (`mutations._bidding_scheme`), so this superset lets a value
# read from get_campaigns round-trip straight into create_campaign / update_campaign instead of
# being rejected at the tool boundary by the schema enum. Kept explicit (not derived from
# BidStrategyType) so static checkers can read the members; keep the short forms in sync with it.
BidStrategyTypeInput = Literal[
    "EnhancedCpc",
    "ManualCpc",
    "MaxClicks",
    "MaxConversions",
    "TargetCpa",
    "MaxConversionValue",
    "TargetRoas",
    "TargetRoasBiddingScheme",
    "MaxConversionValueBiddingScheme",
]
# Conversion-goal bidding / value knobs. Microsoft's enum spellings, used verbatim so they map
# straight onto the API. (Goal status reuses CampaignStatus -- Active / Paused.)
ConversionCountType = Literal["All", "Unique"]
ConversionRevenueType = Literal["FixedValue", "VariableValue", "NoValue"]
# The conversion-goal subtypes create_conversion_goal can build. OfflineConversion is keyed by
# MSCLKID (no UET tag); the four web goals all require a UET TagId. AppInstall / InStoreTransaction
# are deliberately omitted. Microsoft's ConversionGoalType spellings, used verbatim.
ConversionGoalTypeInput = Literal[
    "OfflineConversion",
    "Url",
    "Event",
    "Duration",
    "PagesViewedPerVisit",
]
# Operators for a goal's match expressions (Url goal's UrlOperator, Event goal's category/action/
# label operators). Microsoft's ExpressionOperator spellings, used verbatim.
ExpressionOperatorType = Literal["Equals", "BeginsWith", "RegularExpression", "Contains"]
# Operator for an Event goal's numeric Value comparison. Microsoft's ValueOperator spellings.
ValueOperatorType = Literal["Equals", "LessThan", "GreaterThan"]
# The conversion-goal category (the goal's reporting bucket). The useful subset of Microsoft's
# ConversionGoalCategory enum -- "Unknown" is a read-only/system value and is not offered for
# creation. Spellings used verbatim so they map straight onto the API.
ConversionGoalCategoryType = Literal[
    "None",
    "Purchase",
    "AddToCart",
    "BeginCheckout",
    "Subscribe",
    "SubmitLeadForm",
    "BookAppointment",
    "Signup",
    "RequestQuote",
    "GetDirections",
    "OutboundClick",
    "Contact",
    "PageView",
    "Download",
    "Other",
]
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


class EffectiveUrlSettings(BaseModel):
    """The URL tracking that actually applies to an entity, plus the level that set each field.

    Microsoft resolves URL tracking by override order (keyword > ad > ad group > campaign >
    account): a value set at a deeper level wins, otherwise it inherits from its parent, ultimately
    the account. Reading a single entity is therefore misleading -- ``get_campaigns`` can show
    ``tracking_url_template: null`` while the account-level template is what really applies. This
    flattens that resolution for a campaign (or one of its ad groups) so you see the effective value
    AND where it came from, without manually cross-referencing ``get_account_url_options`` and the
    per-entity reads. Each ``*_source`` is "ad_group", "campaign", or "account" -- or null when the
    field is unset at every level. (URL custom parameters have no account level, so they resolve
    only down to the campaign.)
    """

    level: str  # the entity this was resolved for: "campaign" or "ad_group"
    campaign_id: str
    ad_group_id: str | None = None
    effective_tracking_url_template: str | None = None
    tracking_url_template_source: str | None = None
    effective_final_url_suffix: str | None = None
    final_url_suffix_source: str | None = None
    effective_url_custom_parameters: dict[str, str] | None = None
    url_custom_parameters_source: str | None = None
    # The account-level Microsoft Click ID (msclkid) auto-tagging flag that drives attribution; it
    # has no per-entity override, so it is reported straight from the account.
    msclkid_auto_tagging_enabled: bool | None = None


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
    # The bid strategy (BiddingScheme.Type), e.g. "EnhancedCpc", "MaxConversions". Settable via
    # update_campaign / create_campaign (bid_strategy_type); see the BidStrategyType Literal.
    bid_strategy_type: str | None = None
    # The bid strategy's parameters, read back so a cap/target can be inspected and re-passed on
    # update (which rewrites the scheme whole, else the value clears). max_cpc is the Maximum CPC
    # limit (MaxClicks / MaxConversions / TargetCpa / TargetRoas / MaxConversionValue); target_cpa
    # the Target CPA (TargetCpa / MaxConversions); target_roas the Target ROAS (TargetRoas /
    # MaxConversionValue). null when the scheme lacks that knob or it isn't set.
    max_cpc: float | None = None
    target_cpa: float | None = None
    target_roas: float | None = None
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
        max_cpc_bid = _get(scheme, "MaxCpc", "max_cpc") if scheme is not None else None
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
            max_cpc=(_get(max_cpc_bid, "Amount", "amount") if max_cpc_bid is not None else None),
            target_cpa=(_get(scheme, "TargetCpa", "target_cpa") if scheme is not None else None),
            target_roas=(_get(scheme, "TargetRoas", "target_roas") if scheme is not None else None),
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
    # Ad distribution (the SDK's Network): which Microsoft search surfaces this ad group serves on.
    # A plain str (see the Network Literal) so legacy/in-house values pass through unchanged.
    network: str | None = None
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
            network=_str_or_none(_get(ag, "Network", "network")),
            tracking_url_template=_get(ag, "TrackingUrlTemplate", "tracking_url_template"),
            final_url_suffix=_get(ag, "FinalUrlSuffix", "final_url_suffix"),
            url_custom_parameters=_custom_params(ag),
        )


class KeywordSummary(BaseModel):
    id: str
    text: str | None = None
    match_type: str | None = None
    status: str | None = None
    # Editorial (ad-review) status, distinct from `status` (Active/Paused): a keyword can be
    # Active but Disapproved (rejected, won't serve) or Inactive (pending review). Values:
    # Active (approved), Inactive (under review), ActiveLimited (approved in some markets only),
    # Disapproved (rejected). Check this first when an Active keyword gets zero impressions.
    editorial_status: str | None = None
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
            editorial_status=_str_or_none(_get(kw, "EditorialStatus", "editorial_status")),
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
    # Editorial (ad-review) status, distinct from `status` (Active/Paused): an ad can be Active
    # but Disapproved (rejected, won't serve) or Inactive (pending review). Values: Active
    # (approved), Inactive (under review), ActiveLimited (approved in some markets only),
    # Disapproved (rejected). Check this first when an Active ad gets zero impressions.
    editorial_status: str | None = None
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
            editorial_status=_str_or_none(_get(ad, "EditorialStatus", "editorial_status")),
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


class OfflineConversionInput(BaseModel):
    """One offline conversion to upload via apply_offline_conversions.

    The conversion is attributed to the click that drove it (``click_id`` is the MSCLKID Microsoft
    auto-tags onto landing-page URLs), and counted under the goal whose name matches
    ``conversion_name`` (create one first with an OfflineConversion ``create_conversion_goal``).
    For phone-call tracking, filter the call-center log to qualifying calls (e.g. >=60s) yourself,
    then upload one record per call.
    """

    click_id: str  # the MSCLKID from the ad click (Microsoft Click ID)
    conversion_name: str  # must match an existing OfflineConversion goal's name
    conversion_time: str  # ISO-8601 timestamp; treated as UTC if no offset is given
    value: float | None = None  # conversion value; if set, currency_code is required
    currency_code: str | None = None  # ISO 4217 code for value, e.g. "USD"


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


# ---------------------------------------------------------------- Ad Insight (keyword research)
# These come from the Ad Insight service (the programmatic Keyword Planner), not Campaign
# Management. Every value is a *modeled estimate*, account-scoped, and Microsoft leaves fields
# null when it has no data for a keyword/match type -- so treat missing numbers as "unknown".


class BidEstimate(BaseModel):
    """One match type's bid estimate for a target ad position, plus the traffic that bid buys.

    ``estimated_min_bid`` is the headline number: the suggested bid to reach the requested position
    (the "estimated first page bid" when the request targets ``FirstPage``). The per-week ranges
    bracket the traffic that bid is modeled to deliver.

    Heads-up on ``average_cpc`` / ``ctr``: per Microsoft these are derived from the *top* of the
    range -- ``average_cpc = max_total_cost_per_week / max_clicks_per_week`` and
    ``ctr = max_clicks_per_week / max_impressions_per_week * 100``. So ``average_cpc`` reflects the
    aggressive (max-traffic) end and can sit *above* ``estimated_min_bid`` for very competitive
    keywords -- that is Microsoft's formula, not a max-bid you would pay. The raw min/max cost and
    clicks below let you recompute it for any point in the range.
    """

    match_type: str | None = None
    estimated_min_bid: float | None = None
    # Derived: max_total_cost_per_week / max_clicks_per_week (the avg CPC at the top of the range).
    average_cpc: float | None = None
    # Derived: max_clicks_per_week / max_impressions_per_week * 100.
    ctr: float | None = None
    min_clicks_per_week: float | None = None
    max_clicks_per_week: float | None = None
    min_impressions_per_week: int | None = None
    max_impressions_per_week: int | None = None
    min_total_cost_per_week: float | None = None
    max_total_cost_per_week: float | None = None
    currency_code: str | None = None

    @classmethod
    def from_sdk(cls, e: Any) -> BidEstimate:
        return cls(
            match_type=_str_or_none(_get(e, "MatchType", "match_type")),
            estimated_min_bid=_get(e, "EstimatedMinBid", "estimated_min_bid"),
            average_cpc=_get(e, "AverageCPC", "average_cpc"),
            ctr=_get(e, "CTR", "ctr"),
            min_clicks_per_week=_get(e, "MinClicksPerWeek", "min_clicks_per_week"),
            max_clicks_per_week=_get(e, "MaxClicksPerWeek", "max_clicks_per_week"),
            min_impressions_per_week=_to_int(
                _get(e, "MinImpressionsPerWeek", "min_impressions_per_week")
            ),
            max_impressions_per_week=_to_int(
                _get(e, "MaxImpressionsPerWeek", "max_impressions_per_week")
            ),
            min_total_cost_per_week=_get(e, "MinTotalCostPerWeek", "min_total_cost_per_week"),
            max_total_cost_per_week=_get(e, "MaxTotalCostPerWeek", "max_total_cost_per_week"),
            currency_code=_str_or_none(_get(e, "CurrencyCode", "currency_code")),
        )


class KeywordBidEstimate(BaseModel):
    """Estimated bids for one keyword, one ``BidEstimate`` per requested match type.

    ``estimates`` is empty when Microsoft has no bid data for the keyword.
    """

    keyword: str | None = None
    estimates: list[BidEstimate] = []

    @classmethod
    def from_sdk(cls, k: Any) -> KeywordBidEstimate:
        bids = _get(k, "EstimatedBids", "estimated_bids")
        items = [b for b in bids if b is not None] if isinstance(bids, list) else []
        return cls(
            keyword=_get(k, "Keyword", "keyword"),
            estimates=[BidEstimate.from_sdk(b) for b in items],
        )


class KeywordIdeaSummary(BaseModel):
    """One suggested keyword from the Keyword Planner, with demand and competition signals.

    ``avg_monthly_searches`` is the mean of the trailing ``monthly_search_counts`` window (kept as
    a list so the agent can see seasonality). ``suggested_bid`` is a rough top-of-page bid and
    ``competition`` is the advertiser-density bucket (Low / Medium / High).
    """

    keyword: str | None = None
    source: str | None = None
    avg_monthly_searches: int | None = None
    monthly_search_counts: list[int] | None = None
    suggested_bid: float | None = None
    competition: str | None = None
    relevance: float | None = None
    ad_impression_share: float | None = None

    @classmethod
    def from_sdk(cls, k: Any) -> KeywordIdeaSummary:
        counts = _int_list(_get(k, "MonthlySearchCounts", "monthly_search_counts"))
        return cls(
            keyword=_get(k, "Keyword", "keyword"),
            source=_str_or_none(_get(k, "Source", "source")),
            avg_monthly_searches=_avg(counts),
            monthly_search_counts=counts or None,
            suggested_bid=_get(k, "SuggestedBid", "suggested_bid"),
            competition=_str_or_none(_get(k, "Competition", "competition")),
            relevance=_get(k, "Relevance", "relevance"),
            ad_impression_share=_get(k, "AdImpressionShare", "ad_impression_share"),
        )


class KeywordTrafficEstimate(BaseModel):
    """Modeled weekly traffic for one keyword at a given max CPC, as a min..max bracket.

    Microsoft returns a Minimum and Maximum ``TrafficEstimate`` per keyword; each field below is
    that bracket flattened to ``min_*`` / ``max_*``. ``max_cpc`` echoes the bid the estimate was
    requested at (filled in by the service layer, since the response omits it).
    """

    keyword: str | None = None
    match_type: str | None = None
    max_cpc: float | None = None
    min_clicks: float | None = None
    max_clicks: float | None = None
    min_impressions: float | None = None
    max_impressions: float | None = None
    min_total_cost: float | None = None
    max_total_cost: float | None = None
    min_avg_cpc: float | None = None
    max_avg_cpc: float | None = None
    min_ctr: float | None = None
    max_ctr: float | None = None
    min_avg_position: float | None = None
    max_avg_position: float | None = None

    @classmethod
    def from_sdk(cls, ke: Any) -> KeywordTrafficEstimate:
        kw = _get(ke, "Keyword", "keyword")
        lo = _get(ke, "Minimum", "minimum")
        hi = _get(ke, "Maximum", "maximum")

        def read(obj: Any, *names: str) -> Any:
            """Read a field off a Minimum/Maximum/Keyword that may be absent."""
            return _get(obj, *names) if obj is not None else None

        return cls(
            keyword=read(kw, "Text", "text"),
            match_type=_str_or_none(read(kw, "MatchType", "match_type")),
            min_clicks=read(lo, "Clicks", "clicks"),
            max_clicks=read(hi, "Clicks", "clicks"),
            min_impressions=read(lo, "Impressions", "impressions"),
            max_impressions=read(hi, "Impressions", "impressions"),
            min_total_cost=read(lo, "TotalCost", "total_cost"),
            max_total_cost=read(hi, "TotalCost", "total_cost"),
            min_avg_cpc=read(lo, "AverageCpc", "average_cpc"),
            max_avg_cpc=read(hi, "AverageCpc", "average_cpc"),
            min_ctr=read(lo, "Ctr", "ctr"),
            max_ctr=read(hi, "Ctr", "ctr"),
            min_avg_position=read(lo, "AveragePosition", "average_position"),
            max_avg_position=read(hi, "AveragePosition", "average_position"),
        )


class FirstPageBidCheck(BaseModel):
    """One keyword's bid vs. its estimated first-page bid (the "below first page bid" check).

    ``current_bid`` is the keyword's effective max CPC: its own bid when set, otherwise the ad
    group's default bid (``bid_source`` records which). ``below_first_page_bid`` is True when that
    effective bid sits under ``estimated_first_page_bid`` -- the keyword likely won't show on the
    first page -- and ``None`` when it can't be judged: Microsoft returned no estimate for the
    keyword/match type, or the effective bid is unknown (no keyword bid and no ad-group default).
    ``shortfall`` is how far the bid would need to rise to reach the estimate (only set when below).
    """

    keyword_id: str | None = None
    keyword: str | None = None
    match_type: str | None = None
    status: str | None = None
    editorial_status: str | None = None
    current_bid: float | None = None
    bid_source: str | None = None  # "keyword" (own bid) or "ad_group" (inherited default)
    estimated_first_page_bid: float | None = None
    below_first_page_bid: bool | None = None
    shortfall: float | None = None
    currency_code: str | None = None


class FirstPageBidReport(BaseModel):
    """An ad group's keywords checked against their first-page bid estimates.

    ``keywords`` is ordered with the flagged (below-first-page) entries first and the largest
    ``shortfall`` first, so the bids most in need of a raise surface at the top, then the adequately
    bid keywords, then the undetermined ones. ``undetermined_count`` is keywords Microsoft returned
    no estimate for -- treat those as "unknown", not "adequately bid".
    """

    ad_group_id: str
    target_position: str
    ad_group_default_bid: float | None = None
    currency_code: str | None = None
    keywords_checked: int
    below_first_page_count: int
    undetermined_count: int
    keywords: list[FirstPageBidCheck] = []


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


def _to_int(val: Any) -> int | None:
    """Coerce an int-ish value (Ad Insight reports impression counts as strings) to an int."""
    if val is None:
        return None
    try:
        return int(float(val))
    except TypeError, ValueError:
        return None


def _int_list(val: Any) -> list[int]:
    """Parse a list of int-ish values (e.g. MonthlySearchCounts strings), dropping non-numeric."""
    if not isinstance(val, list):
        return []
    out: list[int] = []
    for v in val:
        n = _to_int(v)
        if n is not None:
            out.append(n)
    return out


def _avg(values: list[int]) -> int | None:
    """Mean of a non-empty int list, rounded to an int; None for an empty list."""
    return round(sum(values) / len(values)) if values else None


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
