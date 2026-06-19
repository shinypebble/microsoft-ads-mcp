"""Editorial (ad-review) status is surfaced on ads and keywords, separate from entity status.

This is the "can an Active entity actually serve?" signal -- Disapproved/Inactive ads and keywords
report status="Active" but won't run. The API returns EditorialStatus by default (verified live),
so the summaries just need to read and unwrap it.
"""

from __future__ import annotations

from types import SimpleNamespace

from openapi_client.models.campaign.ad_editorial_status import AdEditorialStatus
from openapi_client.models.campaign.keyword_editorial_status import KeywordEditorialStatus

from microsoft_ads_mcp.domain.entities import AdSummary, KeywordSummary


def test_ad_summary_surfaces_editorial_status_separate_from_status() -> None:
    ad = SimpleNamespace(
        id=76553736627801,
        type="ResponsiveSearch",
        status="Active",
        editorial_status=AdEditorialStatus.DISAPPROVED,
    )
    summary = AdSummary.from_sdk(ad)
    assert summary.status == "Active"  # entity status (Active/Paused) is unchanged
    assert summary.editorial_status == "Disapproved"  # ...but it would not actually serve


def test_keyword_summary_surfaces_editorial_status() -> None:
    kw = SimpleNamespace(
        id=76554248594440,
        text="compare internet providers",
        match_type="Exact",
        status="Active",
        editorial_status=KeywordEditorialStatus.INACTIVE,  # pending review
    )
    summary = KeywordSummary.from_sdk(kw)
    assert summary.status == "Active"
    assert summary.editorial_status == "Inactive"


def test_editorial_status_absent_stays_none() -> None:
    ad = SimpleNamespace(id=1, type="ResponsiveSearch", status="Paused")
    kw = SimpleNamespace(id=2, text="x", match_type="Broad", status="Paused")
    assert AdSummary.from_sdk(ad).editorial_status is None
    assert KeywordSummary.from_sdk(kw).editorial_status is None
