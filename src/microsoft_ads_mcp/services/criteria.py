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
from openapi_client.models.campaign.campaign import Campaign
from openapi_client.models.campaign.campaign_criterion_type import CampaignCriterionType
from openapi_client.models.campaign.day import Day
from openapi_client.models.campaign.day_time_criterion import DayTimeCriterion
from openapi_client.models.campaign.delete_campaign_criterions_request import (
    DeleteCampaignCriterionsRequest,
)
from openapi_client.models.campaign.device_criterion import DeviceCriterion
from openapi_client.models.campaign.get_campaign_criterions_by_ids_request import (
    GetCampaignCriterionsByIdsRequest,
)
from openapi_client.models.campaign.intent_option import IntentOption
from openapi_client.models.campaign.location_criterion import LocationCriterion
from openapi_client.models.campaign.location_intent_criterion import LocationIntentCriterion
from openapi_client.models.campaign.minute import Minute
from openapi_client.models.campaign.negative_campaign_criterion import NegativeCampaignCriterion
from openapi_client.models.campaign.update_campaign_criterions_request import (
    UpdateCampaignCriterionsRequest,
)
from openapi_client.models.campaign.update_campaigns_request import UpdateCampaignsRequest

from ..api.client import CAMPAIGN, MsAdsClient
from ..domain.entities import (
    AdScheduleInput,
    AdScheduleSettings,
    AdScheduleSummary,
    DeviceBidAdjustmentSummary,
    LocationCriterionSummary,
    LocationIntentSummary,
    MutationResult,
)
from . import as_list, first_attr, flat_partial_errors, nested_partial_errors
from .campaigns import get_campaign_by_id

# Ad-schedule minutes are a 15-minute-granularity enum; map the integers an agent passes onto it.
_MINUTE_BY_INT = {0: Minute.ZERO, 15: Minute.FIFTEEN, 30: Minute.THIRTY, 45: Minute.FORTYFIVE}

# Microsoft's three device-criterion names (case-sensitive). "Smartphones" is mobile; there is no
# "Mobile". The aliases let an agent say "mobile"/"desktop"/"tablet" and get the canonical name.
_ALL_DEVICES = ("Computers", "Smartphones", "Tablets")
_DEVICE_ALIASES = {
    "computers": "Computers",
    "computer": "Computers",
    "desktop": "Computers",
    "desktops": "Computers",
    "pc": "Computers",
    "smartphones": "Smartphones",
    "smartphone": "Smartphones",
    "mobile": "Smartphones",
    "phone": "Smartphones",
    "phones": "Smartphones",
    "tablets": "Tablets",
    "tablet": "Tablets",
}
# Device bid multipliers accept a wider floor than other criterions: -100 excludes the device.
_DEVICE_MIN_MULTIPLIER = -100.0
_DEVICE_MAX_MULTIPLIER = 900.0


def _normalize_device(name: str) -> str:
    """Resolve a friendly device name (e.g. "mobile") to Microsoft's canonical value."""
    canonical = _DEVICE_ALIASES.get(name.strip().lower())
    if canonical is None:
        raise ValueError(
            f"device must be one of Computers, Smartphones, Tablets (got {name!r}); "
            "'mobile' maps to Smartphones, 'desktop' to Computers"
        )
    return canonical


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
    # call_raw: a rejected criterion returns CampaignCriterionIds=[null] + PartialErrors, which the
    # typed model can't parse (its id list is non-nullable strings); the raw dict surfaces it.
    resp = client.call_raw(
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
    # call_raw: a rejected criterion returns CampaignCriterionIds=[null] + PartialErrors, which the
    # typed model can't parse (its id list is non-nullable strings); the raw dict surfaces it.
    resp = client.call_raw(
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


def _campaign_time_zone(client: MsAdsClient, campaign_id: str) -> tuple[str | None, bool | None]:
    """Return the campaign's ``(time_zone, ad_schedule_use_searcher_time_zone)`` for context.

    Reads just this campaign (GetCampaignsByIds) rather than scanning the whole account list.
    """
    c = get_campaign_by_id(client, campaign_id)
    if c is None:
        return None, None
    return c.time_zone, c.ad_schedule_use_searcher_time_zone


def get_ad_schedules(client: MsAdsClient, *, campaign_id: str) -> AdScheduleSettings:
    """Read a campaign's ad-schedule (dayparting) windows and their time-zone context."""
    resp = client.call(
        CAMPAIGN,
        "get_campaign_criterions_by_ids",
        GetCampaignCriterionsByIdsRequest(
            campaign_id=campaign_id,
            campaign_criterion_ids=None,
            criterion_type=CampaignCriterionType.DAYTIME,
        ),
    )
    items = as_list(first_attr(resp, "CampaignCriterions", "campaign_criterions"))
    schedules = [AdScheduleSummary.from_sdk(c) for c in items if c is not None]
    time_zone, use_searcher = _campaign_time_zone(client, campaign_id)
    return AdScheduleSettings(
        campaign_id=str(campaign_id),
        time_zone=time_zone,
        use_searcher_time_zone=use_searcher,
        schedules=schedules,
    )


def _minute(value: int) -> Minute:
    """Map an integer minute to the 15-minute-granularity ``Minute`` enum (raises if invalid)."""
    try:
        return _MINUTE_BY_INT[value]
    except KeyError:
        raise ValueError(
            f"minute must be one of 0, 15, 30, 45 (15-minute granularity); got {value}"
        ) from None


def add_ad_schedules(
    client: MsAdsClient,
    *,
    campaign_id: str,
    schedules: list[AdScheduleInput],
    use_searcher_time_zone: bool | None = None,
) -> MutationResult:
    """Add ad-schedule (dayparting) windows to a campaign.

    Each window restricts serving to a day and time range; multiple windows are additive. Times
    run in the campaign time zone unless ``use_searcher_time_zone`` is set true.

    The campaign-level ``use_searcher_time_zone`` flag is changed only after the windows are added
    successfully: building the criterions (which validates the 15-minute granularity) and the add
    call both happen first, so a rejected input or a failed add never leaves the campaign's
    time-zone flag flipped while reporting failure.
    """
    criterions = []
    for s in schedules:
        daytime = DayTimeCriterion(
            type="DayTimeCriterion",
            day=Day(s.day),
            from_hour=s.from_hour,
            from_minute=_minute(s.from_minute),
            to_hour=s.to_hour,
            to_minute=_minute(s.to_minute),
        )
        criterion_bid = (
            BidMultiplier(type="BidMultiplier", multiplier=s.bid_adjustment)
            if s.bid_adjustment
            else None
        )
        criterions.append(
            BiddableCampaignCriterion(
                type="BiddableCampaignCriterion",
                campaign_id=campaign_id,
                criterion=daytime,
                criterion_bid=criterion_bid,
            )
        )
    # call_raw: a rejected window (e.g. one overlapping an existing same-day window) returns
    # CampaignCriterionIds=[null] + PartialErrors, which the typed model can't parse (its id list
    # is non-nullable strings); the raw dict lets the reason surface instead of crashing.
    resp = client.call_raw(
        CAMPAIGN,
        "add_campaign_criterions",
        # Adds go under the umbrella "Targets" type; the specific "DayTime" type is only valid for
        # the get filter (the API 400s on it for add/update/delete, like the other targets).
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
    if errors or not ids:
        return MutationResult(
            ok=False,
            message="Add ad schedules failed",
            ids=ids,
            partial_errors=errors,
        )

    # Windows landed cleanly -- now it is safe to flip the campaign-level time-zone flag (it
    # governs how every schedule on the campaign is interpreted).
    if use_searcher_time_zone is not None:
        tz_resp = client.call(
            CAMPAIGN,
            "update_campaigns",
            UpdateCampaignsRequest(
                account_id=client.account_id,
                campaigns=[
                    Campaign(
                        id=campaign_id, ad_schedule_use_searcher_time_zone=use_searcher_time_zone
                    )
                ],
            ),
        )
        tz_errors = flat_partial_errors(tz_resp)
        if tz_errors:
            return MutationResult(
                ok=False,
                message=(
                    f"Added {len(ids)} ad-schedule window(s) but failed to set the time-zone flag"
                ),
                ids=ids,
                partial_errors=tz_errors,
            )

    return MutationResult(
        ok=True,
        message=f"Added {len(ids)} ad-schedule window(s) to campaign {campaign_id}",
        ids=ids,
        partial_errors=errors,
    )


def remove_ad_schedules(
    client: MsAdsClient, *, campaign_id: str, criterion_ids: list[str]
) -> MutationResult:
    """Remove ad-schedule (dayparting) windows from a campaign by criterion id."""
    resp = client.call(
        CAMPAIGN,
        "delete_campaign_criterions",
        # Deletes use the umbrella "Targets" type (not the specific "DayTime" type).
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
            f"Removed {len(criterion_ids)} ad-schedule window(s) from campaign {campaign_id}"
            if not errors
            else "Remove ad schedules failed"
        ),
        ids=[str(i) for i in criterion_ids],
        partial_errors=errors,
    )


def replace_ad_schedule(
    client: MsAdsClient,
    *,
    campaign_id: str,
    criterion_id: str,
    new_window: AdScheduleInput,
    use_searcher_time_zone: bool | None = None,
) -> MutationResult:
    """Replace one dayparting window: remove the old criterion, then add the new window.

    The API rejects adding a window that overlaps an existing same-day window, so the only safe
    order is remove-then-add (briefly leaving that window uncovered). If the remove fails nothing
    is changed; if the add fails *after* a successful remove, the result says so clearly -- the old
    window is already gone, so the caller knows coverage is currently dropped and can re-add.
    """
    removed = remove_ad_schedules(client, campaign_id=campaign_id, criterion_ids=[criterion_id])
    if not removed.ok:
        return removed
    added = add_ad_schedules(
        client,
        campaign_id=campaign_id,
        schedules=[new_window],
        use_searcher_time_zone=use_searcher_time_zone,
    )
    if not added.ids:
        # No id came back -> the new window was rejected (e.g. it overlaps another existing window).
        # The old window is already gone, so that slot is now uncovered; tell the caller to re-add.
        return MutationResult(
            ok=False,
            message=(
                f"Removed old ad-schedule window {criterion_id} but adding the new window failed "
                f"-- campaign {campaign_id} now has no window where the old one was; re-add it"
            ),
            ids=[],
            partial_errors=added.partial_errors,
        )
    # The new window landed (added.ids is non-empty). Pass add_ad_schedules' result through as-is:
    # ok=True on full success, or its own ok=False + the real id when only the optional time-zone
    # flag update failed -- never the misleading "re-add" message (the window already exists).
    return added


def get_device_bid_adjustments(
    client: MsAdsClient, *, campaign_id: str
) -> list[DeviceBidAdjustmentSummary]:
    """List a campaign's device bid adjustments (Computers / Smartphones / Tablets).

    An empty list means no device modifier is set (every device serves at the base bid). Microsoft
    normally creates all three together, so you usually see three rows or none.
    """
    resp = client.call(
        CAMPAIGN,
        "get_campaign_criterions_by_ids",
        GetCampaignCriterionsByIdsRequest(
            campaign_id=campaign_id,
            campaign_criterion_ids=None,
            criterion_type=CampaignCriterionType.DEVICE,
        ),
    )
    items = as_list(first_attr(resp, "CampaignCriterions", "campaign_criterions"))
    return [DeviceBidAdjustmentSummary.from_sdk(c) for c in items if c is not None]


def set_device_bid_adjustment(
    client: MsAdsClient, *, campaign_id: str, device: str, bid_adjustment: float
) -> MutationResult:
    """Set a campaign's bid adjustment for one device type (e.g. a mobile modifier).

    ``bid_adjustment`` is a percent modifier from -100 to 900; -100 excludes the device. Microsoft
    does not allow changing a device criterion's ``DeviceName`` on update, and device criterions
    are created as a set of three, so:

    * if the target device criterion already exists, its multiplier is updated in place;
    * otherwise the missing device criterions are added together (all three when none exist), the
      target getting ``bid_adjustment`` and any others a neutral 0.
    """
    canonical = _normalize_device(device)
    if not _DEVICE_MIN_MULTIPLIER <= bid_adjustment <= _DEVICE_MAX_MULTIPLIER:
        raise ValueError(
            f"bid_adjustment must be between {_DEVICE_MIN_MULTIPLIER:.0f} and "
            f"{_DEVICE_MAX_MULTIPLIER:.0f} percent (got {bid_adjustment})"
        )

    existing = {
        s.device: s
        for s in get_device_bid_adjustments(client, campaign_id=campaign_id)
        if s.device is not None
    }
    target = existing.get(canonical)
    if target is not None and target.criterion_id is not None:
        # Update the existing criterion in place. DeviceName must match the existing value (the API
        # forbids changing it), so we re-send the canonical name. Like every target criterion, this
        # goes under the umbrella "Targets" type, not the specific "Device" type.
        cc = BiddableCampaignCriterion(
            type="BiddableCampaignCriterion",
            id=target.criterion_id,
            campaign_id=campaign_id,
            criterion=DeviceCriterion(type="DeviceCriterion", device_name=canonical),
            criterion_bid=BidMultiplier(type="BidMultiplier", multiplier=bid_adjustment),
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
                f"Set {canonical} bid adjustment to {bid_adjustment:g}% on campaign {campaign_id}"
                if not errors
                else "Set device bid adjustment failed"
            ),
            ids=[target.criterion_id],
            partial_errors=errors,
        )

    # No criterion for this device yet: add the missing device types together (Microsoft requires
    # the three to be added as a set), the target with its multiplier and any others neutral at 0.
    criterions = [
        BiddableCampaignCriterion(
            type="BiddableCampaignCriterion",
            campaign_id=campaign_id,
            criterion=DeviceCriterion(type="DeviceCriterion", device_name=name),
            criterion_bid=BidMultiplier(
                type="BidMultiplier",
                multiplier=bid_adjustment if name == canonical else 0.0,
            ),
        )
        for name in _ALL_DEVICES
        if name not in existing
    ]
    # call_raw: a rejected criterion returns CampaignCriterionIds=[null] + PartialErrors, which the
    # typed model can't parse (its id list is non-nullable strings); the raw dict surfaces it.
    resp = client.call_raw(
        CAMPAIGN,
        "add_campaign_criterions",
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
    return MutationResult(
        ok=bool(ids) and not errors,
        message=(
            f"Set {canonical} bid adjustment to {bid_adjustment:g}% on campaign {campaign_id}"
            if ids and not errors
            else "Set device bid adjustment failed"
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
