"""Conversion-goal and UET-tag flows: read, create, and update in place (rename, status, value).

Conversion goals are polymorphic (UrlGoal, EventGoal, ...). To update one we fetch it to learn
its concrete subtype, then rebuild a minimal instance of that *same* class carrying only the id
and the changed fields -- the subtype's ``__init__`` re-stamps the required ``Type``
discriminator, so the request stays a clean partial. Creation builds the right subclass directly
(its ``__init__`` stamps the ``Type``). UET tags are a flat model, so a plain partial suffices.
Offline conversions (the bid-eligible phone-call path) are imported by MSCLKID against a goal name.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from openapi_client.models.campaign.add_conversion_goals_request import (
    AddConversionGoalsRequest,
)
from openapi_client.models.campaign.apply_offline_conversions_request import (
    ApplyOfflineConversionsRequest,
)
from openapi_client.models.campaign.conversion_goal_additional_field import (
    ConversionGoalAdditionalField,
)
from openapi_client.models.campaign.conversion_goal_revenue import ConversionGoalRevenue
from openapi_client.models.campaign.conversion_goal_type import ConversionGoalType
from openapi_client.models.campaign.duration_goal import DurationGoal
from openapi_client.models.campaign.event_goal import EventGoal
from openapi_client.models.campaign.get_conversion_goals_by_ids_request import (
    GetConversionGoalsByIdsRequest,
)
from openapi_client.models.campaign.get_conversion_goals_by_tag_ids_request import (
    GetConversionGoalsByTagIdsRequest,
)
from openapi_client.models.campaign.get_uet_tags_by_ids_request import GetUetTagsByIdsRequest
from openapi_client.models.campaign.offline_conversion import OfflineConversion
from openapi_client.models.campaign.offline_conversion_goal import OfflineConversionGoal
from openapi_client.models.campaign.pages_viewed_per_visit_goal import PagesViewedPerVisitGoal
from openapi_client.models.campaign.uet_tag import UetTag
from openapi_client.models.campaign.update_conversion_goals_request import (
    UpdateConversionGoalsRequest,
)
from openapi_client.models.campaign.update_uet_tags_request import UpdateUetTagsRequest
from openapi_client.models.campaign.url_goal import UrlGoal

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import (
    ConversionGoalSummary,
    MutationResult,
    OfflineConversionInput,
    UetTagSummary,
)
from . import as_list, first_attr, flat_partial_errors

# Curated goal-type filter the get-calls accept. The full OR of every type (and the bare app/
# in-store members) is rejected with 400; this set covers the common web/app goal types.
_GOAL_TYPES = (
    ConversionGoalType.URL
    | ConversionGoalType.EVENT
    | ConversionGoalType.DURATION
    | ConversionGoalType.PAGESVIEWEDPERVISIT
    | ConversionGoalType.APPINSTALL
    | ConversionGoalType.OFFLINECONVERSION
)

# The goal subtypes create_conversion_goal can build, keyed by the friendly ``goal_type``. Each
# subclass stamps its own ``Type`` discriminator in ``__init__``. AppInstall / InStoreTransaction
# are intentionally not offered.
_GOAL_SUBCLASSES = {
    "OfflineConversion": OfflineConversionGoal,
    "Url": UrlGoal,
    "Event": EventGoal,
    "Duration": DurationGoal,
    "PagesViewedPerVisit": PagesViewedPerVisitGoal,
}
# The web (UET-backed) goals require a UET TagId. OfflineConversion does not (keyed by MSCLKID).
_WEB_GOAL_TYPES = frozenset({"Url", "Event", "Duration", "PagesViewedPerVisit"})

# GoalCategory is an "additional field": the get-calls only return it when it's requested via
# ReturnAdditionalFields, otherwise it comes back null even when set. Request it so the summary's
# goal_category is populated.
_GOAL_ADDITIONAL_FIELDS = ConversionGoalAdditionalField.GOALCATEGORY


def get_conversion_goals(
    client: MsAdsClient, *, goal_ids: list[str] | None = None
) -> list[ConversionGoalSummary]:
    """List conversion goals. Pass ``goal_ids`` for specific goals, else list by UET tag.

    Goals are reachable by id or by their UET tag; with no ``goal_ids`` we enumerate the
    account's UET tags and fetch their goals (the by-ids call requires explicit ids).
    """
    if goal_ids:
        resp = client.call(
            CAMPAIGN,
            "get_conversion_goals_by_ids",
            GetConversionGoalsByIdsRequest(
                conversion_goal_ids=goal_ids,
                conversion_goal_types=_GOAL_TYPES,
                return_additional_fields=_GOAL_ADDITIONAL_FIELDS,
            ),
        )
    else:
        tags = client.call(CAMPAIGN, "get_uet_tags_by_ids", GetUetTagsByIdsRequest(tag_ids=None))
        tag_ids = [
            str(first_attr(t, "Id", "id"))
            for t in as_list(first_attr(tags, "UetTags", "uet_tags"))
            if t is not None and first_attr(t, "Id", "id") is not None
        ]
        if not tag_ids:
            return []
        resp = client.call(
            CAMPAIGN,
            "get_conversion_goals_by_tag_ids",
            GetConversionGoalsByTagIdsRequest(
                tag_ids=tag_ids,
                conversion_goal_types=_GOAL_TYPES,
                return_additional_fields=_GOAL_ADDITIONAL_FIELDS,
            ),
        )
    items = as_list(first_attr(resp, "ConversionGoals", "conversion_goals"))
    return [ConversionGoalSummary.from_sdk(g) for g in items if g is not None]


def _build_revenue(
    rev_type: Any,
    rev_value: float | None,
    rev_currency: str | None,
) -> ConversionGoalRevenue:
    """Build a Revenue object from a type plus optional value/currency, enforcing the type rules.

    NoValue forbids a Value (and currency is meaningless), so only the type is sent. FixedValue
    requires a value. Sub-fields are only put on the request when set, so the SDK never emits
    them as explicit nulls.
    """
    if rev_type is None:
        raise ValueError(
            "revenue_type is required (FixedValue, VariableValue, or NoValue) to set revenue"
        )
    kwargs: dict[str, Any] = {"type": rev_type}
    type_name = str(getattr(rev_type, "value", rev_type))
    if type_name == "NoValue":
        # NoValue forbids a Value; currency is meaningless, so send only the type.
        return ConversionGoalRevenue(**kwargs)
    if type_name == "FixedValue" and rev_value is None:
        raise ValueError("revenue_value is required when revenue_type is 'FixedValue'")
    if rev_value is not None:
        kwargs["value"] = float(rev_value)
    if rev_currency is not None:
        kwargs["currency_code"] = rev_currency
    return ConversionGoalRevenue(**kwargs)


def _merge_revenue(
    goal: Any,
    revenue_type: str | None,
    revenue_value: float | None,
    revenue_currency_code: str | None,
) -> ConversionGoalRevenue:
    """Build a Revenue object, overlaying the caller's fields onto the goal's current revenue.

    The API replaces the whole Revenue object on update (a non-empty Revenue overwrites every
    existing revenue property), so we re-send the goal's current sub-fields and change only the
    ones the caller passed -- otherwise omitting a sub-field silently clears it.
    """
    existing = first_attr(goal, "Revenue", "revenue")
    rev_type = revenue_type
    rev_value = revenue_value
    rev_currency = revenue_currency_code
    if existing is not None:
        if rev_type is None:
            rev_type = first_attr(existing, "Type", "type")
        if rev_value is None:
            rev_value = first_attr(existing, "Value", "value")
        if rev_currency is None:
            rev_currency = first_attr(existing, "CurrencyCode", "currency_code")
    return _build_revenue(rev_type, rev_value, rev_currency)


def update_conversion_goal(
    client: MsAdsClient,
    *,
    goal_id: str,
    name: str | None = None,
    status: str | None = None,
    exclude_from_bidding: bool | None = None,
    count_type: str | None = None,
    conversion_window_in_minutes: int | None = None,
    revenue_type: str | None = None,
    revenue_value: float | None = None,
    revenue_currency_code: str | None = None,
) -> MutationResult:
    """Update a conversion goal in place (rename, pause, or change its bidding/value fields).

    ``exclude_from_bidding`` is the inverse of the web UI's "Include in conversions" checkbox --
    the single switch for whether the goal steers automated bidding. Pass ``False`` to count it
    in the Conversions column and ECPC/tCPA bid math, ``True`` to drop it from both (it still
    reports under All conversions). Only the fields passed are sent (a partial update); revenue
    sub-fields are merged over the goal's current revenue (the API replaces the whole Revenue
    object, so unspecified sub-fields are re-sent rather than cleared).
    """
    if status is not None and status not in ("Active", "Paused"):
        raise ValueError("status must be 'Active' or 'Paused'")
    has_revenue = (
        revenue_type is not None or revenue_value is not None or revenue_currency_code is not None
    )
    # Cheap no-op guard before the round-trip.
    if not has_revenue and all(
        v is None
        for v in (name, status, exclude_from_bidding, count_type, conversion_window_in_minutes)
    ):
        raise ValueError("update_conversion_goal requires at least one field to change")
    fetched = client.call(
        CAMPAIGN,
        "get_conversion_goals_by_ids",
        GetConversionGoalsByIdsRequest(
            conversion_goal_ids=[goal_id], conversion_goal_types=_GOAL_TYPES
        ),
    )
    goals = [g for g in as_list(first_attr(fetched, "ConversionGoals", "conversion_goals")) if g]
    if not goals:
        return MutationResult(ok=False, message=f"Conversion goal {goal_id} not found")
    goal = goals[0]
    # ``exclude_from_bidding=False`` is a meaningful value (it *includes* the goal in bidding), so
    # filter on ``is not None`` rather than truthiness to keep it.
    fields: dict[str, Any] = {
        k: v
        for k, v in {
            "name": name,
            "status": status,
            "exclude_from_bidding": exclude_from_bidding,
            "count_type": count_type,
            "conversion_window_in_minutes": conversion_window_in_minutes,
        }.items()
        if v is not None
    }
    if has_revenue:
        fields["revenue"] = _merge_revenue(goal, revenue_type, revenue_value, revenue_currency_code)
    # Rebuild a minimal partial of the same concrete subtype so the Type discriminator is set.
    updated = type(goal)(id=goal_id, **fields)
    resp = client.call(
        CAMPAIGN,
        "update_conversion_goals",
        UpdateConversionGoalsRequest(conversion_goals=[updated]),
    )
    errors = flat_partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"Conversion goal {goal_id} updated" if not errors else "Update failed",
        ids=[str(goal_id)],
        partial_errors=errors,
    )


def create_conversion_goal(
    client: MsAdsClient,
    *,
    name: str,
    goal_type: str,
    tag_id: str | None = None,
    status: str | None = None,
    count_type: str | None = None,
    conversion_window_in_minutes: int | None = None,
    goal_category: str | None = None,
    revenue_type: str | None = None,
    revenue_value: float | None = None,
    revenue_currency_code: str | None = None,
    exclude_from_bidding: bool | None = None,
    url_expression: str | None = None,
    url_operator: str = "Equals",
    category_expression: str | None = None,
    category_operator: str | None = None,
    action_expression: str | None = None,
    action_operator: str | None = None,
    label_expression: str | None = None,
    label_operator: str | None = None,
    value: float | None = None,
    value_operator: str | None = None,
    minimum_duration_in_seconds: int | None = None,
    minimum_pages_viewed: int | None = None,
) -> MutationResult:
    """Create a conversion goal of ``goal_type``.

    The four web goals (Url/Event/Duration/PagesViewedPerVisit) require a UET ``tag_id``;
    OfflineConversion is keyed by MSCLKID and takes no tag. New goals are created **Active** (the
    SDK default) -- unlike spending entities, a goal does not spend, and a paused goal silently
    fails to record conversions; pass ``status="Paused"`` to override. ``exclude_from_bidding`` is
    omitted unless set so the goal inherits Microsoft's default (False = included in bidding);
    ``False`` is preserved if passed explicitly.
    """
    subclass = _GOAL_SUBCLASSES.get(goal_type)
    if subclass is None:
        raise ValueError("goal_type must be one of: " + ", ".join(_GOAL_SUBCLASSES))
    if status is not None and status not in ("Active", "Paused"):
        raise ValueError("status must be 'Active' or 'Paused'")
    is_web = goal_type in _WEB_GOAL_TYPES
    if is_web and not tag_id:
        raise ValueError(f"{goal_type} goals require a UET tag_id (from get_uet_tags)")
    if not is_web and tag_id:
        raise ValueError("OfflineConversion goals are keyed by MSCLKID and take no tag_id")

    # Reject type-specific fields that belong to a different goal_type -- silently dropping them
    # would be a confusing no-op. (url_operator has a default, so it's not checked here.)
    foreign: dict[str, tuple[str, Any]] = {
        "url_expression": ("Url", url_expression),
        "category_expression": ("Event", category_expression),
        "category_operator": ("Event", category_operator),
        "action_expression": ("Event", action_expression),
        "action_operator": ("Event", action_operator),
        "label_expression": ("Event", label_expression),
        "label_operator": ("Event", label_operator),
        "value": ("Event", value),
        "value_operator": ("Event", value_operator),
        "minimum_duration_in_seconds": ("Duration", minimum_duration_in_seconds),
        "minimum_pages_viewed": ("PagesViewedPerVisit", minimum_pages_viewed),
    }
    for field, (owner, val) in foreign.items():
        if val is not None and owner != goal_type:
            raise ValueError(f"{field} is only valid for {owner} goals, not {goal_type}")

    # Shared fields: name always; others only when set. exclude_from_bidding uses ``is not None`` so
    # False (include in bidding) is preserved rather than dropped.
    fields: dict[str, Any] = {"name": name}
    for k, v in {
        "status": status,
        "count_type": count_type,
        "conversion_window_in_minutes": conversion_window_in_minutes,
        "goal_category": goal_category,
        "exclude_from_bidding": exclude_from_bidding,
        "tag_id": tag_id,
    }.items():
        if v is not None:
            fields[k] = v
    if revenue_type is not None or revenue_value is not None or revenue_currency_code is not None:
        fields["revenue"] = _build_revenue(revenue_type, revenue_value, revenue_currency_code)

    # Type-specific fields.
    if goal_type == "Url":
        if not url_expression:
            raise ValueError("Url goals require url_expression")
        fields["url_expression"] = url_expression
        fields["url_operator"] = url_operator
    elif goal_type == "Event":
        if not (category_expression or action_expression or label_expression):
            raise ValueError(
                "Event goals require at least one of category_expression, action_expression, "
                "or label_expression"
            )
        for k, v in {
            "category_expression": category_expression,
            "category_operator": category_operator,
            "action_expression": action_expression,
            "action_operator": action_operator,
            "label_expression": label_expression,
            "label_operator": label_operator,
            "value": value,
            "value_operator": value_operator,
        }.items():
            if v is not None:
                fields[k] = v
    elif goal_type == "Duration":
        if minimum_duration_in_seconds is None:
            raise ValueError("Duration goals require minimum_duration_in_seconds")
        fields["minimum_duration_in_seconds"] = minimum_duration_in_seconds
    elif goal_type == "PagesViewedPerVisit":
        if minimum_pages_viewed is None:
            raise ValueError("PagesViewedPerVisit goals require minimum_pages_viewed")
        fields["minimum_pages_viewed"] = minimum_pages_viewed
    # OfflineConversion needs no type-specific fields (it keys on MSCLKID at upload time).

    goal = subclass(**fields)
    # call_raw (not call): a rejected goal comes back as ConversionGoalIds=[null] + PartialErrors,
    # which the typed response model can't parse (its id list is non-nullable strings). Reading the
    # raw JSON lets the partial error surface as a clean result instead of a deserialization crash.
    resp = client.call_raw(
        CAMPAIGN,
        "add_conversion_goals",
        AddConversionGoalsRequest(conversion_goals=[goal]),
    )
    ids = [
        str(i)
        for i in as_list(first_attr(resp, "ConversionGoalIds", "conversion_goal_ids"))
        if i is not None
    ]
    errors = flat_partial_errors(resp)
    return MutationResult(
        ok=bool(ids) and not errors,
        message=(
            f"Created {goal_type} conversion goal '{name}'"
            if ids and not errors
            else "Create conversion goal failed"
        ),
        ids=ids,
        partial_errors=errors,
    )


def _parse_conversion_time(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; a naive value (no offset) is treated as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"conversion_time must be ISO-8601, got {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def apply_offline_conversions(
    client: MsAdsClient, *, conversions: list[OfflineConversionInput]
) -> MutationResult:
    """Import offline conversions by MSCLKID against an OfflineConversion goal (the bid-eligible
    phone-call path).

    Each record is attributed to its click (``click_id`` = MSCLKID) and counted under the goal
    whose name equals ``conversion_name`` (create it first with create_conversion_goal). Apply the
    >=60s (or whatever) call filter yourself before uploading. ``conversion_time`` is ISO-8601 and
    treated as UTC when no offset is given; ``currency_code`` is required when a ``value`` is set.
    """
    if not conversions:
        raise ValueError("apply_offline_conversions requires at least one conversion")
    records: list[OfflineConversion] = []
    for c in conversions:
        when = _parse_conversion_time(c.conversion_time)
        if c.value is not None and not c.currency_code:
            raise ValueError(f"currency_code is required when value is set (click_id {c.click_id})")
        oc_fields: dict[str, Any] = {
            "microsoft_click_id": c.click_id,
            "conversion_name": c.conversion_name,
            "conversion_time": when,
        }
        if c.value is not None:
            oc_fields["conversion_value"] = c.value
        if c.currency_code is not None:
            oc_fields["conversion_currency_code"] = c.currency_code
        records.append(OfflineConversion(**oc_fields))
    resp = client.call(
        CAMPAIGN,
        "apply_offline_conversions",
        ApplyOfflineConversionsRequest(offline_conversions=records),
    )
    errors = flat_partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=(
            f"Applied {len(records)} offline conversion(s)"
            if not errors
            else "Apply offline conversions failed"
        ),
        ids=[],
        partial_errors=errors,
    )


def get_uet_tags(client: MsAdsClient, *, tag_ids: list[str] | None = None) -> list[UetTagSummary]:
    """List UET tags. Pass ``tag_ids`` to fetch specific tags (omit for all)."""
    resp = client.call(CAMPAIGN, "get_uet_tags_by_ids", GetUetTagsByIdsRequest(tag_ids=tag_ids))
    items = as_list(first_attr(resp, "UetTags", "uet_tags"))
    return [UetTagSummary.from_sdk(t) for t in items if t is not None]


def update_uet_tag(
    client: MsAdsClient,
    *,
    tag_id: str,
    name: str | None = None,
    description: str | None = None,
) -> MutationResult:
    """Update a UET tag's name and/or description in place."""
    fields: dict[str, Any] = {
        k: v for k, v in {"name": name, "description": description}.items() if v is not None
    }
    tag = UetTag(id=tag_id, **fields)
    resp = client.call(CAMPAIGN, "update_uet_tags", UpdateUetTagsRequest(uet_tags=[tag]))
    errors = flat_partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"UET tag {tag_id} updated" if not errors else "Update failed",
        ids=[str(tag_id)],
        partial_errors=errors,
    )
