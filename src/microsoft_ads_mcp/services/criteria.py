"""Location (ZIP/geo) targeting via campaign criterions.

ZIP targeting is a criterion attached per campaign -- a ``BiddableCampaignCriterion`` (target,
optionally with a bid adjustment) or ``NegativeCampaignCriterion`` (exclude) wrapping a
``LocationCriterion``. There is no reusable shared "ZIP list"; criterions are replicated per
campaign. On add you supply only the ``LocationId`` (type/name are derived); resolve ZIPs to
ids first with the geo helper.
"""

from __future__ import annotations

from openapi_client.models.campaign.add_campaign_criterions_request import (
    AddCampaignCriterionsRequest,
)
from openapi_client.models.campaign.biddable_campaign_criterion import BiddableCampaignCriterion
from openapi_client.models.campaign.campaign_criterion_type import CampaignCriterionType
from openapi_client.models.campaign.delete_campaign_criterions_request import (
    DeleteCampaignCriterionsRequest,
)
from openapi_client.models.campaign.fixed_bid import FixedBid
from openapi_client.models.campaign.get_campaign_criterions_by_ids_request import (
    GetCampaignCriterionsByIdsRequest,
)
from openapi_client.models.campaign.location_criterion import LocationCriterion
from openapi_client.models.campaign.negative_campaign_criterion import NegativeCampaignCriterion

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import LocationCriterionSummary, MutationResult
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
            criterions.append(
                BiddableCampaignCriterion(
                    type="BiddableCampaignCriterion",
                    campaign_id=campaign_id,
                    criterion=location,
                    criterion_bid=FixedBid(type="FixedBid", amount=bid_adjustment),
                )
            )
    resp = client.call(
        CAMPAIGN,
        "add_campaign_criterions",
        AddCampaignCriterionsRequest(
            campaign_criterions=criterions, criterion_type=CampaignCriterionType.LOCATION
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


def remove_location_targets(
    client: MsAdsClient, *, campaign_id: str, criterion_ids: list[str]
) -> MutationResult:
    """Remove location targets/exclusions from a campaign by criterion id."""
    resp = client.call(
        CAMPAIGN,
        "delete_campaign_criterions",
        DeleteCampaignCriterionsRequest(
            campaign_id=campaign_id,
            campaign_criterion_ids=criterion_ids,
            criterion_type=CampaignCriterionType.LOCATION,
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
