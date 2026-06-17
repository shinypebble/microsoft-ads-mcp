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
from openapi_client.models.reporting.campaign_performance_report_request import (
    CampaignPerformanceReportRequest,
)
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
    poll_interval_seconds: float = 5.0,
    timeout_seconds: float = 180.0,
) -> ReportResult:
    """Submit a report, poll until ready, download the CSV, and return parsed rows."""
    if report_type not in _REPORTS:
        raise ValueError(f"report_type must be one of {', '.join(REPORT_TYPES)}")
    request_cls, scope_cls, default_cols = _REPORTS[report_type]
    cols = columns or default_cols

    scope = scope_cls(account_ids=[int(client.account_id)])
    report_request = request_cls(
        format="Csv",
        report_name=f"{report_type} {date_range}",
        return_only_complete_data=False,
        exclude_report_header=True,
        exclude_report_footer=True,
        exclude_column_headers=False,
        scope=scope,
        time=ReportTime(predefined_time=date_range),
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
        date_range=date_range,
        columns=columns_out or cols,
        row_count=len(rows),
        rows=[ReportRow(values=r) for r in rows],
    )


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
