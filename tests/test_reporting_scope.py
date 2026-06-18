"""Reporting scope/time builders: custom date ranges and entity filters."""

from __future__ import annotations

import pytest
from openapi_client.models.reporting.account_through_ad_group_report_scope import (
    AccountThroughAdGroupReportScope,
)
from openapi_client.models.reporting.account_through_campaign_report_scope import (
    AccountThroughCampaignReportScope,
)

from microsoft_ads_mcp.services import reporting


def test_account_scope_is_default() -> None:
    scope = reporting._build_scope(
        AccountThroughCampaignReportScope, account="123", campaign_id=None, ad_group_id=None
    )
    assert scope.account_ids == ["123"] and scope.campaigns is None


def test_campaign_filter_scope() -> None:
    scope = reporting._build_scope(
        AccountThroughCampaignReportScope, account="123", campaign_id="487928625", ad_group_id=None
    )
    assert scope.campaigns[0].account_id == "123"
    assert scope.campaigns[0].campaign_id == "487928625"


def test_ad_group_filter_requires_capable_scope() -> None:
    with pytest.raises(ValueError, match="ad_group_id filtering"):
        reporting._build_scope(
            AccountThroughCampaignReportScope, account="123", campaign_id=None, ad_group_id="9"
        )


def test_ad_group_filter_on_capable_scope() -> None:
    scope = reporting._build_scope(
        AccountThroughAdGroupReportScope,
        account="123",
        campaign_id="487928625",
        ad_group_id="1224857457251120",
    )
    ag = scope.ad_groups[0]
    assert ag.account_id == "123" and ag.ad_group_id == "1224857457251120"
    assert ag.campaign_id == "487928625"


def test_predefined_time() -> None:
    time, label = reporting._build_time("LastWeek", None, None)
    assert label == "LastWeek"
    assert time.predefined_time == "LastWeek" and time.custom_date_range_start is None


def test_custom_range_time() -> None:
    time, label = reporting._build_time("LastMonth", "2026-06-01", "2026-06-17")
    assert label == "2026-06-01..2026-06-17"
    assert time.predefined_time is None
    start = time.custom_date_range_start
    assert (start.year, start.month, start.day) == (2026, 6, 1)


def test_custom_range_needs_both_bounds() -> None:
    with pytest.raises(ValueError, match="both start_date and end_date"):
        reporting._build_time("LastMonth", "2026-06-01", None)


def test_bad_date_format_rejected() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        reporting._to_date("06/01/2026")
