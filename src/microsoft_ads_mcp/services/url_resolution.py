"""Resolve the *effective* URL tracking for an entity across Microsoft's inheritance chain.

URL tracking -- the tracking template, Final URL suffix, and URL custom parameters -- can be set at
several levels, and Microsoft applies them by override order: keyword > ad > ad group > campaign >
account. A blank value at one level inherits from its parent, so reading one entity is misleading:
``get_campaigns`` can report ``tracking_url_template: null`` while the account-level template is
what actually drives click tracking / attribution. This walks the chain for a campaign (or one of
its ad groups) and reports both the effective value and the level that set it.

Reuses the existing reads (``campaigns.get_campaign_by_id`` / ``campaigns.get_ad_groups`` /
``account_properties.get_account_url_options``) -- no new SDK request shapes. Keyword/ad-level
resolution is intentionally out of scope here (it needs a by-ids parent lookup); campaign and ad
group cover the common case.
"""

from __future__ import annotations

from typing import Any

from ..api.client import MsAdsClient
from ..domain.entities import EffectiveUrlSettings
from . import account_properties, campaigns


def _first_set(*candidates: tuple[str, Any]) -> tuple[Any, str | None]:
    """Return the first ``(value, source)`` whose value is set (non-empty), else ``(None, None)``.

    Candidates are ordered deepest-first (ad group, then campaign, then account), so the first set
    value is the one Microsoft's override order applies. Empty strings / empty dicts count as unset.
    """
    for source, value in candidates:
        if value:
            return value, source
    return None, None


def get_effective_url_settings(
    client: MsAdsClient, *, campaign_id: str, ad_group_id: str | None = None
) -> EffectiveUrlSettings:
    """Resolve the effective tracking template / Final URL suffix / URL custom parameters for a
    campaign, or for one of its ad groups when ``ad_group_id`` is given, reporting which level set
    each field (ad group > campaign > account).
    """
    account = account_properties.get_account_url_options(client)
    campaign = campaigns.get_campaign_by_id(client, campaign_id)
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found")

    ad_group = None
    if ad_group_id is not None:
        ad_group = next(
            (
                ag
                for ag in campaigns.get_ad_groups(client, campaign_id)
                if ag.id == str(ad_group_id)
            ),
            None,
        )
        if ad_group is None:
            raise ValueError(f"Ad group {ad_group_id} not found in campaign {campaign_id}")

    # Build each field's candidate chain deepest-first. The ad-group level only exists when an
    # ad_group_id was given; the account has no url_custom_parameters, so that chain stops at the
    # campaign.
    template_chain: list[tuple[str, Any]] = []
    suffix_chain: list[tuple[str, Any]] = []
    params_chain: list[tuple[str, Any]] = []
    if ad_group is not None:
        template_chain.append(("ad_group", ad_group.tracking_url_template))
        suffix_chain.append(("ad_group", ad_group.final_url_suffix))
        params_chain.append(("ad_group", ad_group.url_custom_parameters))
    template_chain.append(("campaign", campaign.tracking_url_template))
    suffix_chain.append(("campaign", campaign.final_url_suffix))
    params_chain.append(("campaign", campaign.url_custom_parameters))
    template_chain.append(("account", account.tracking_url_template))
    suffix_chain.append(("account", account.final_url_suffix))

    template, template_source = _first_set(*template_chain)
    suffix, suffix_source = _first_set(*suffix_chain)
    params, params_source = _first_set(*params_chain)

    return EffectiveUrlSettings(
        level="ad_group" if ad_group is not None else "campaign",
        campaign_id=str(campaign_id),
        ad_group_id=str(ad_group_id) if ad_group_id is not None else None,
        effective_tracking_url_template=template,
        tracking_url_template_source=template_source,
        effective_final_url_suffix=suffix,
        final_url_suffix_source=suffix_source,
        effective_url_custom_parameters=params,
        url_custom_parameters_source=params_source,
        msclkid_auto_tagging_enabled=account.msclkid_auto_tagging_enabled,
    )
