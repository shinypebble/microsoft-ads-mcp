"""Location (ZIP/geo) targeting via campaign criterions.

ZIP targeting is a criterion attached per campaign -- a ``BiddableCampaignCriterion`` (target,
optionally with a bid adjustment) or ``NegativeCampaignCriterion`` (exclude) wrapping a
``LocationCriterion``. There is no reusable shared "ZIP list"; criterions are replicated per
campaign. On add you supply only the ``LocationId`` (type/name are derived); resolve ZIPs to
ids first with the geo helper.
"""

from __future__ import annotations

from typing import Any

from openapi_client.models.campaign.add_campaign_criterions_request import (
    AddCampaignCriterionsRequest,
)
from openapi_client.models.campaign.bid_multiplier import BidMultiplier
from openapi_client.models.campaign.biddable_campaign_criterion import BiddableCampaignCriterion
from openapi_client.models.campaign.campaign_criterion_type import CampaignCriterionType
from openapi_client.models.campaign.delete_campaign_criterions_request import (
    DeleteCampaignCriterionsRequest,
)
from openapi_client.models.campaign.get_campaign_criterions_by_ids_request import (
    GetCampaignCriterionsByIdsRequest,
)
from openapi_client.models.campaign.intent_option import IntentOption
from openapi_client.models.campaign.location_criterion import LocationCriterion
from openapi_client.models.campaign.location_intent_criterion import LocationIntentCriterion
from openapi_client.models.campaign.negative_campaign_criterion import NegativeCampaignCriterion
from openapi_client.models.campaign.update_campaign_criterions_request import (
    UpdateCampaignCriterionsRequest,
)

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import (
    LocationCriterionSummary,
    LocationIntentSummary,
    MutationResult,
)
from . import as_list, first_attr, flat_partial_errors, nested_partial_errors


def get_location_targets(
    client: MsAdsClient, *, campaign_id: str
) -> list[LocationCriterionSummary]:
    """List the location targets/exclusions attached to a campaign."""
    resp = client.call(
        CAMPAIGN,
        "get_campaign_criterions_by_ids",
        GetCampaignCriterionsByIdsRequest(
            campaign_id=campaign_id,
            campaign_criterion_ids=None,
            criterion_type=CampaignCriterionType.LOCATION,
        ),
    )
    items = as_list(first_attr(resp, "CampaignCriterions", "campaign_criterions"))
    return [LocationCriterionSummary.from_sdk(c) for c in items if c is not None]


def add_location_targets(
    client: MsAdsClient,
    *,
    campaign_id: str,
    location_ids: list[str],
    bid_adjustment: float = 0.0,
    exclude: bool = False,
) -> MutationResult:
    """Target (or exclude) the given Microsoft LocationIds on a campaign.

    ``bid_adjustment`` is a percent modifier applied to targeted locations (ignored when
    ``exclude`` is true).
    """
    criterions = []
    for loc in location_ids:
        location = LocationCriterion(type="LocationCriterion", location_id=str(loc))
        if exclude:
            criterions.append(
                NegativeCampaignCriterion(
                    type="NegativeCampaignCriterion", campaign_id=campaign_id, criterion=location
                )
            )
        else:
            # A location bid adjustment is a percent multiplier (BidMultiplier), not an absolute
            # bid; omit it entirely when no adjustment is requested.
            criterion_bid = (
                BidMultiplier(type="BidMultiplier", multiplier=bid_adjustment)
                if bid_adjustment
                else None
            )
            criterions.append(
                BiddableCampaignCriterion(
                    type="BiddableCampaignCriterion",
                    campaign_id=campaign_id,
                    criterion=location,
                    criterion_bid=criterion_bid,
                )
            )
    resp = client.call(
        CAMPAIGN,
        "add_campaign_criterions",
        # Adds go under the umbrella "Targets" type; the specific "Location" type is only valid
        # for get/delete filtering (the API rejects it on add with CampaignCriterionTypeInvalid).
        AddCampaignCriterionsRequest(
            campaign_criterions=criterions, criterion_type=CampaignCriterionType.TARGETS
        ),
    )
    errors = nested_partial_errors(resp)
    ids = [
        str(i)
        for i in as_list(first_attr(resp, "CampaignCriterionIds", "campaign_criterion_ids"))
        if i is not None
    ]
    verb = "Excluded" if exclude else "Targeted"
    return MutationResult(
        ok=bool(ids) and not errors,
        message=(
            f"{verb} {len(ids)} location(s) on campaign {campaign_id}"
            if ids
            else "Add location targets failed"
        ),
        ids=ids,
        partial_errors=errors,
    )


def _get_location_intent_criterion(client: MsAdsClient, *, campaign_id: str) -> Any:
    """Fetch the campaign's single location-intent ``BiddableCampaignCriterion`` (or None).

    Microsoft auto-creates exactly one ``LocationIntent`` criterion per campaign (its id equals
    the campaign id), so this normally returns it; we still tolerate an empty list defensively.
    """
    resp = client.call(
        CAMPAIGN,
        "get_campaign_criterions_by_ids",
        GetCampaignCriterionsByIdsRequest(
            campaign_id=campaign_id,
            campaign_criterion_ids=None,
            criterion_type=CampaignCriterionType.LOCATIONINTENT,
        ),
    )
    items = as_list(first_attr(resp, "CampaignCriterions", "campaign_criterions"))
    return next((c for c in items if c is not None), None)


def get_location_intent(client: MsAdsClient, *, campaign_id: str) -> LocationIntentSummary | None:
    """Read the campaign's location-intent setting (presence vs. search interest)."""
    crit = _get_location_intent_criterion(client, campaign_id=campaign_id)
    return LocationIntentSummary.from_sdk(crit) if crit is not None else None


def set_location_intent(
    client: MsAdsClient, *, campaign_id: str, intent_option: str
) -> MutationResult:
    """Set the campaign's location-intent option (who sees the ad relative to its locations).

    There is at most one location-intent criterion per campaign. Microsoft auto-creates it (with
    the default ``PeopleInOrSearchingForOrViewingPages``) when the campaign gets its first
    criterion, so we normally update the existing one in place; if a campaign has no criterions
    yet there may be none to read, in which case we add it instead.
    """
    criterion = LocationIntentCriterion(
        type="LocationIntentCriterion", intent_option=IntentOption(intent_option)
    )
    existing = _get_location_intent_criterion(client, campaign_id=campaign_id)
    if existing is not None:
        # Update in place. The criterion id equals the campaign id for the auto-created criterion,
        # but read it back rather than assume. NOTE: add/update/delete of any *target* criterion
        # (location, location intent, radius, ...) must use the umbrella ``Targets`` type -- the
        # specific ``LocationIntent`` type is only valid for get filtering, and the API 400s on it.
        criterion_id = str(first_attr(existing, "Id", "id"))
        cc = BiddableCampaignCriterion(
            type="BiddableCampaignCriterion",
            id=criterion_id,
            campaign_id=campaign_id,
            criterion=criterion,
        )
        resp = client.call(
            CAMPAIGN,
            "update_campaign_criterions",
            UpdateCampaignCriterionsRequest(
                campaign_criterions=[cc], criterion_type=CampaignCriterionType.TARGETS
            ),
        )
        errors = nested_partial_errors(resp)
        return MutationResult(
            ok=not errors,
            message=(
                f"Set location intent to {intent_option} on campaign {campaign_id}"
                if not errors
                else "Set location intent failed"
            ),
            ids=[criterion_id],
            partial_errors=errors,
        )

    # No criterion exists yet (campaign has no criterions): add one (also under ``Targets``).
    cc = BiddableCampaignCriterion(
        type="BiddableCampaignCriterion", campaign_id=campaign_id, criterion=criterion
    )
    resp = client.call(
        CAMPAIGN,
        "add_campaign_criterions",
        AddCampaignCriterionsRequest(
            campaign_criterions=[cc], criterion_type=CampaignCriterionType.TARGETS
        ),
    )
    errors = nested_partial_errors(resp)
    ids = [
        str(i)
        for i in as_list(first_attr(resp, "CampaignCriterionIds", "campaign_criterion_ids"))
        if i is not None
    ]
    return MutationResult(
        ok=bool(ids) and not errors,
        message=(
            f"Set location intent to {intent_option} on campaign {campaign_id}"
            if ids and not errors
            else "Set location intent failed"
        ),
        ids=ids,
        partial_errors=errors,
    )


def remove_location_targets(
    client: MsAdsClient, *, campaign_id: str, criterion_ids: list[str]
) -> MutationResult:
    """Remove location targets/exclusions from a campaign by criterion id."""
    resp = client.call(
        CAMPAIGN,
        "delete_campaign_criterions",
        # Deletes also use the umbrella "Targets" type (not the specific "Location" type).
        DeleteCampaignCriterionsRequest(
            campaign_id=campaign_id,
            campaign_criterion_ids=criterion_ids,
            criterion_type=CampaignCriterionType.TARGETS,
        ),
    )
    errors = flat_partial_errors(resp)
    return MutationResult(
        ok=not errors,
        message=(
            f"Removed {len(criterion_ids)} location target(s) from campaign {campaign_id}"
            if not errors
            else "Remove location targets failed"
        ),
        ids=[str(i) for i in criterion_ids],
        partial_errors=errors,
    )
