"""Conversion-goal and UET-tag flows: read, and rename (the common rebrand need).

Conversion goals are polymorphic (UrlGoal, EventGoal, ...). To rename one we fetch it to learn
its concrete subtype, then rebuild a minimal instance of that *same* class carrying only the id
and new name -- the subtype's ``__init__`` re-stamps the required ``Type`` discriminator, so the
request stays a clean partial. UET tags are a flat model, so a plain partial suffices.
"""

from __future__ import annotations

from typing import Any

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


def update_conversion_goal(client: MsAdsClient, *, goal_id: str, name: str) -> MutationResult:
    """Rename a conversion goal in place."""
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
