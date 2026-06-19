"""Performance reporting: submit a report, poll to completion, download and parse the rows.

The original server stopped at handing back a download URL the agent could not read. This
flow runs the whole loop and returns parsed rows. CSV headers/footers are excluded at request
time so the payload is exactly one column-header row followed by data rows.
"""

from __future__ import annotations

import csv
import io
import time
import zipfile
from typing import Any

import requests
from openapi_client.models.reporting.account_through_ad_group_report_scope import (
    AccountThroughAdGroupReportScope,
)
from openapi_client.models.reporting.account_through_campaign_report_scope import (
    AccountThroughCampaignReportScope,
)
from openapi_client.models.reporting.ad_group_report_scope import AdGroupReportScope
from openapi_client.models.reporting.campaign_performance_report_request import (
    CampaignPerformanceReportRequest,
)
from openapi_client.models.reporting.campaign_report_scope import CampaignReportScope
from openapi_client.models.reporting.date import Date
from openapi_client.models.reporting.geographic_performance_report_request import (
    GeographicPerformanceReportRequest,
)
from openapi_client.models.reporting.keyword_performance_report_request import (
    KeywordPerformanceReportRequest,
)
from openapi_client.models.reporting.poll_generate_report_request import (
    PollGenerateReportRequest,
)
from openapi_client.models.reporting.report_time import ReportTime
from openapi_client.models.reporting.search_query_performance_report_request import (
    SearchQueryPerformanceReportRequest,
)
from openapi_client.models.reporting.submit_generate_report_request import (
    SubmitGenerateReportRequest,
)

from ..api.client import REPORTING, MsAdsClient
from ..api.errors import MsAdsApiError
from ..domain.entities import ReportResult, ReportRow
from . import first_attr

# report_type -> (request class, scope class, default columns).
_REPORTS: dict[str, tuple[type, type, list[str]]] = {
    "campaign": (
        CampaignPerformanceReportRequest,
        AccountThroughCampaignReportScope,
        ["CampaignName", "Impressions", "Clicks", "Ctr", "AverageCpc", "Spend", "Conversions"],
    ),
    "keyword": (
        KeywordPerformanceReportRequest,
        AccountThroughAdGroupReportScope,
        [
            "Keyword",
            "AdGroupName",
            "CampaignName",
            "Impressions",
            "Clicks",
            "Spend",
            "QualityScore",
        ],
    ),
    "search_query": (
        SearchQueryPerformanceReportRequest,
        AccountThroughAdGroupReportScope,
        ["SearchQuery", "Keyword", "CampaignName", "Impressions", "Clicks", "Spend", "Conversions"],
    ),
    "geographic": (
        GeographicPerformanceReportRequest,
        AccountThroughAdGroupReportScope,
        ["Country", "State", "City", "CampaignName", "Impressions", "Clicks", "Spend"],
    ),
}

REPORT_TYPES = tuple(_REPORTS.keys())


def run_performance_report(
    client: MsAdsClient,
    *,
    report_type: str,
    date_range: str = "LastMonth",
    columns: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_group_id: str | None = None,
    poll_interval_seconds: float = 5.0,
    timeout_seconds: float = 180.0,
) -> ReportResult:
    """Submit a report, poll until ready, download the CSV, and return parsed rows.

    Time window: a ``start_date``/``end_date`` pair (each ``YYYY-MM-DD``) takes precedence over
    the predefined ``date_range``. Scope: ``campaign_id`` / ``ad_group_id`` narrow the report to
    one entity; otherwise the whole account (``account_id`` or the configured one) is reported.
    """
    if report_type not in _REPORTS:
        raise ValueError(f"report_type must be one of {', '.join(REPORT_TYPES)}")
    request_cls, scope_cls, default_cols = _REPORTS[report_type]
    cols = columns or default_cols
    account = str(account_id or client.account_id)

    scope = _build_scope(
        scope_cls, account=account, campaign_id=campaign_id, ad_group_id=ad_group_id
    )
    time, window_label = _build_time(date_range, start_date, end_date)
    report_request = request_cls(
        format="Csv",
        report_name=f"{report_type} {window_label}",
        return_only_complete_data=False,
        exclude_report_header=True,
        exclude_report_footer=True,
        exclude_column_headers=False,
        scope=scope,
        time=time,
        columns=cols,
    )

    submit = client.call(
        REPORTING,
        "submit_generate_report",
        SubmitGenerateReportRequest(report_request=report_request),
    )
    request_id = first_attr(submit, "ReportRequestId", "report_request_id")
    if not request_id:
        raise MsAdsApiError(0, "Report submission did not return a request id")

    download_url = _poll(client, request_id, poll_interval_seconds, timeout_seconds)
    columns_out, rows = _download_and_parse(download_url)
    return ReportResult(
        report_type=report_type,
        date_range=window_label,
        columns=columns_out or cols,
        row_count=len(rows),
        rows=[ReportRow(values=r) for r in rows],
    )


def _build_scope(
    scope_cls: type,
    *,
    account: str,
    campaign_id: str | None,
    ad_group_id: str | None,
) -> Any:
    """Narrow the report to one ad group or campaign, else the whole account."""
    if ad_group_id is not None:
        if "ad_groups" not in scope_cls.model_fields:
            raise ValueError(
                "ad_group_id filtering needs report_type 'keyword', 'search_query', or 'geographic'"
            )
        scope_kwargs: dict[str, Any] = {"account_id": account, "ad_group_id": str(ad_group_id)}
        if campaign_id is not None:
            scope_kwargs["campaign_id"] = str(campaign_id)
        return scope_cls(ad_groups=[AdGroupReportScope(**scope_kwargs)])
    if campaign_id is not None:
        return scope_cls(
            campaigns=[CampaignReportScope(account_id=account, campaign_id=str(campaign_id))]
        )
    return scope_cls(account_ids=[account])


def _build_time(
    date_range: str, start_date: str | None, end_date: str | None
) -> tuple[ReportTime, str]:
    """Custom YYYY-MM-DD range when both bounds are given, else the predefined range."""
    if start_date or end_date:
        if not (start_date and end_date):
            raise ValueError("provide both start_date and end_date for a custom range")
        time = ReportTime(
            custom_date_range_start=_to_date(start_date),
            custom_date_range_end=_to_date(end_date),
        )
        return time, f"{start_date}..{end_date}"
    return ReportTime(predefined_time=date_range), date_range


def _to_date(value: str) -> Date:
    parts = value.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")
    year, month, day = (int(p) for p in parts)
    return Date(year=year, month=month, day=day)


def _poll(client: MsAdsClient, request_id: Any, interval: float, timeout: float) -> str:
    """Poll the report status until Success, raising on Error or timeout. Returns the URL."""
    deadline = time.monotonic() + timeout
    while True:
        resp = client.call(
            REPORTING,
            "poll_generate_report",
            PollGenerateReportRequest(report_request_id=request_id),
        )
        status_obj = first_attr(resp, "ReportRequestStatus", "report_request_status")
        status = first_attr(status_obj, "Status", "status")
        if status == "Success":
            url = first_attr(status_obj, "ReportDownloadUrl", "report_download_url")
            if not url:
                # A report with no rows can complete with no download URL.
                return ""
            return str(url)
        if status == "Error":
            raise MsAdsApiError(0, f"Report generation failed (request {request_id})")
        if time.monotonic() >= deadline:
            raise MsAdsApiError(0, f"Report not ready after {timeout:g}s (last status: {status})")
        time.sleep(interval)


def _download_and_parse(url: str) -> tuple[list[str], list[dict[str, str]]]:
    """Download the report zip, extract the CSV, and parse it into header + row dicts."""
    if not url:
        return [], []
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    content = resp.content

    csv_text: str
    if content[:2] == b"PK":  # zip archive
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            name = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                return [], []
            csv_text = zf.read(name).decode("utf-8-sig")
    else:
        csv_text = content.decode("utf-8-sig")

    reader = csv.reader(io.StringIO(csv_text))
    rows = [r for r in reader if r and any(cell.strip() for cell in r)]
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    parsed = [dict(zip(header, row, strict=False)) for row in rows[1:]]
    return header, parsed
