"""Negative-keyword flows: add, list, and remove campaign- or ad-group-level negatives.

These are *entity-level* negatives (attached directly to a campaign or ad group), not a shared
negative-keyword list. Microsoft models them as an ``EntityNegativeKeyword`` graph and returns
*nested* partial errors (one error collection per entity), so the parsing differs from the flat
``PartialErrors`` used elsewhere.
"""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.add_negative_keywords_to_entities_request import (
    AddNegativeKeywordsToEntitiesRequest,
)
from openapi_client.models.campaign.delete_negative_keywords_from_entities_request import (
    DeleteNegativeKeywordsFromEntitiesRequest,
)
from openapi_client.models.campaign.entity_negative_keyword import EntityNegativeKeyword
from openapi_client.models.campaign.get_negative_keywords_by_entity_ids_request import (
    GetNegativeKeywordsByEntityIdsRequest,
)
from openapi_client.models.campaign.negative_keyword import NegativeKeyword

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import (
    MatchType,
    MutationResult,
    NegativeEntityType,
    NegativeKeywordSummary,
)
from . import as_list, first_attr, nested_partial_errors


def _check_entity_type(entity_type: str) -> None:
    if entity_type not in ("Campaign", "AdGroup"):
        raise ValueError("entity_type must be 'Campaign' or 'AdGroup'")


def _nested_ids(resp: Any) -> list[str]:
    """Flatten ``NegativeKeywordIds`` (a list of IdCollection) into a flat id list."""
    out: list[str] = []
    for coll in as_list(first_attr(resp, "NegativeKeywordIds", "negative_keyword_ids")):
        for i in as_list(first_attr(coll, "Ids", "ids")):
            if i is not None:
                out.append(str(i))
    return out


def add_negative_keywords(
    client: MsAdsClient,
    *,
    entity_id: str,
    entity_type: NegativeEntityType,
    keywords: list[str],
    match_type: MatchType = "Exact",
) -> MutationResult:
    """Attach negative keywords to a campaign or ad group."""
    _check_entity_type(entity_type)
    nks = [
        NegativeKeyword(type="NegativeKeyword", text=text, match_type=match_type)
        for text in keywords
    ]
    entity = EntityNegativeKeyword(
        entity_id=entity_id, entity_type=entity_type, negative_keywords=nks
    )
    # call_raw: a rejected negative returns a null id (with the reason in NestedPartialErrors),
    # which the typed nested-id model can't parse (its ids are non-nullable strings); the raw dict
    # surfaces it instead of crashing.
    resp = client.call_raw(
        CAMPAIGN,
        "add_negative_keywords_to_entities",
        AddNegativeKeywordsToEntitiesRequest(entity_negative_keywords=[entity]),
    )
    errors = nested_partial_errors(resp)
    ids = _nested_ids(resp)
    return MutationResult(
        ok=bool(ids) and not errors,
        message=(
            f"Added {len(ids)} negative keyword(s) to {entity_type.lower()} {entity_id}"
            if ids
            else "Add negative keywords failed"
        ),
        ids=ids,
        partial_errors=errors,
    )


def get_negative_keywords(
    client: MsAdsClient,
    *,
    entity_ids: list[str],
    entity_type: NegativeEntityType,
    parent_entity_id: str | None = None,
) -> list[NegativeKeywordSummary]:
    """List negative keywords on campaigns or ad groups.

    For ``entity_type="AdGroup"`` Microsoft requires ``parent_entity_id`` (the campaign id).
    """
    _check_entity_type(entity_type)
    if entity_type == "AdGroup" and not parent_entity_id:
        raise ValueError("parent_entity_id (the campaign id) is required for ad-group negatives")
    resp = client.call(
        CAMPAIGN,
        "get_negative_keywords_by_entity_ids",
        GetNegativeKeywordsByEntityIdsRequest(
            entity_type=entity_type, entity_ids=entity_ids, parent_entity_id=parent_entity_id
        ),
    )
    out: list[NegativeKeywordSummary] = []
    for entity in as_list(first_attr(resp, "EntityNegativeKeywords", "entity_negative_keywords")):
        eid = first_attr(entity, "EntityId", "entity_id")
        for nk in as_list(first_attr(entity, "NegativeKeywords", "negative_keywords")):
            out.append(NegativeKeywordSummary.from_sdk(nk, entity_id=eid, entity_type=entity_type))
    return out


def remove_negative_keywords(
    client: MsAdsClient,
    *,
    entity_id: str,
    entity_type: NegativeEntityType,
    keyword_ids: list[str],
) -> MutationResult:
    """Remove negative keywords from a campaign or ad group, identified by id."""
    _check_entity_type(entity_type)
    nks = [NegativeKeyword(type="NegativeKeyword", id=str(k)) for k in keyword_ids]
    entity = EntityNegativeKeyword(
        entity_id=entity_id, entity_type=entity_type, negative_keywords=nks
    )
    resp = client.call(
        CAMPAIGN,
        "delete_negative_keywords_from_entities",
        DeleteNegativeKeywordsFromEntitiesRequest(entity_negative_keywords=[entity]),
    )
    errors = nested_partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=(
            f"Removed {len(keyword_ids)} negative keyword(s) from {entity_type.lower()} {entity_id}"
            if not errors
            else "Remove negative keywords failed"
        ),
        ids=[str(k) for k in keyword_ids],
        partial_errors=errors,
    )
