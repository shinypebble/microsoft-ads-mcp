"""Conversion-goal and UET-tag flows: read, and rename (the common rebrand need).

Conversion goals are polymorphic (UrlGoal, EventGoal, ...). To rename one we fetch it to learn
its concrete subtype, then rebuild a minimal instance of that *same* class carrying only the id
and new name -- the subtype's ``__init__`` re-stamps the required ``Type`` discriminator, so the
request stays a clean partial. UET tags are a flat model, so a plain partial suffices.
"""

from __future__ import annotations

from functools import reduce
from operator import or_
from typing import Any

from openapi_client.models.campaign.conversion_goal_type import ConversionGoalType
from openapi_client.models.campaign.get_conversion_goals_by_ids_request import (
    GetConversionGoalsByIdsRequest,
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


def _all_goal_types() -> ConversionGoalType:
    """Every conversion goal type OR'd together (the type filter the get-call expects)."""
    return reduce(or_, ConversionGoalType)


def get_conversion_goals(
    client: MsAdsClient, *, goal_ids: list[str] | None = None
) -> list[ConversionGoalSummary]:
    """List conversion goals (all types). Pass ``goal_ids`` to fetch specific goals."""
    resp = client.call(
        CAMPAIGN,
        "get_conversion_goals_by_ids",
        GetConversionGoalsByIdsRequest(
            conversion_goal_ids=goal_ids, conversion_goal_types=_all_goal_types()
        ),
    )
    items = as_list(first_attr(resp, "ConversionGoals", "conversion_goals"))
    return [ConversionGoalSummary.from_sdk(g) for g in items if g is not None]


def update_conversion_goal(client: MsAdsClient, *, goal_id: str, name: str) -> MutationResult:
    """Rename a conversion goal in place."""
    fetched = client.call(
        CAMPAIGN,
        "get_conversion_goals_by_ids",
        GetConversionGoalsByIdsRequest(
            conversion_goal_ids=[goal_id], conversion_goal_types=_all_goal_types()
        ),
    )
    goals = [g for g in as_list(first_attr(fetched, "ConversionGoals", "conversion_goals")) if g]
    if not goals:
        return MutationResult(ok=False, message=f"Conversion goal {goal_id} not found")
    # Rebuild a minimal partial of the same concrete subtype so the Type discriminator is set.
    updated = type(goals[0])(id=goal_id, name=name)
    resp = client.call(
        CAMPAIGN,
        "update_conversion_goals",
        UpdateConversionGoalsRequest(conversion_goals=[updated]),
    )
    errors = flat_partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=f"Conversion goal {goal_id} renamed to {name!r}" if not errors else "Update failed",
        ids=[str(goal_id)],
        partial_errors=errors,
    )


def get_uet_tags(client: MsAdsClient, *, tag_ids: list[str] | None = None) -> list[UetTagSummary]:
    """List UET tags. Pass ``tag_ids`` to fetch specific tags (omit for all)."""
    resp = client.call(
        CAMPAIGN, "get_uet_tags_by_ids", GetUetTagsByIdsRequest(tag_ids=tag_ids)
    )
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
