"""Conversion-goal and UET-tag flows: read, and update in place (rename, status, bidding/value).

Conversion goals are polymorphic (UrlGoal, EventGoal, ...). To update one we fetch it to learn
its concrete subtype, then rebuild a minimal instance of that *same* class carrying only the id
and the changed fields -- the subtype's ``__init__`` re-stamps the required ``Type``
discriminator, so the request stays a clean partial. UET tags are a flat model, so a plain
partial suffices.
"""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.conversion_goal_revenue import ConversionGoalRevenue
from openapi_client.models.campaign.conversion_goal_type import ConversionGoalType
from openapi_client.models.campaign.get_conversion_goals_by_ids_request import (
    GetConversionGoalsByIdsRequest,
)
from openapi_client.models.campaign.get_conversion_goals_by_tag_ids_request import (
    GetConversionGoalsByTagIdsRequest,
)
from openapi_client.models.campaign.get_uet_tags_by_ids_request import GetUetTagsByIdsRequest
from openapi_client.models.campaign.uet_tag import UetTag
from openapi_client.models.campaign.update_conversion_goals_request import (
    UpdateConversionGoalsRequest,
)
from openapi_client.models.campaign.update_uet_tags_request import UpdateUetTagsRequest

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import ConversionGoalSummary, MutationResult, UetTagSummary
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
                conversion_goal_ids=goal_ids, conversion_goal_types=_GOAL_TYPES
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
            GetConversionGoalsByTagIdsRequest(tag_ids=tag_ids, conversion_goal_types=_GOAL_TYPES),
        )
    items = as_list(first_attr(resp, "ConversionGoals", "conversion_goals"))
    return [ConversionGoalSummary.from_sdk(g) for g in items if g is not None]


def _merge_revenue(
    goal: Any,
    revenue_type: str | None,
    revenue_value: float | None,
    revenue_currency_code: str | None,
) -> ConversionGoalRevenue:
    """Build a Revenue object, overlaying the caller's fields onto the goal's current revenue.

    The API replaces the whole Revenue object on update (a non-empty Revenue overwrites every
    existing revenue property), so we re-send the goal's current sub-fields and change only the
    ones the caller passed -- otherwise omitting a sub-field silently clears it. Sub-fields are
    only put on the request when set, so the SDK never emits them as explicit nulls.
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
