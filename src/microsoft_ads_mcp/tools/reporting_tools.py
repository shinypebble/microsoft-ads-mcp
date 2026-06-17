"""Reporting tool: submit, poll, download, and parse a performance report."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..api.client import get_client
from ..domain.entities import ReportResult
from ..services import reporting
from ._common import guarded


def register(mcp: FastMCP) -> None:
    @mcp.tool(tags={"read"}, annotations=ToolAnnotations(readOnlyHint=True))
    def run_performance_report(
        report_type: str = "campaign",
        date_range: str = "LastMonth",
        columns: list[str] | None = None,
    ) -> ReportResult:
        """Run a performance report end-to-end and return the parsed rows.

        Unlike a raw submit, this submits the report, polls until it is ready, downloads the
        CSV, and parses it — so the rows come back inline.

        Args:
            report_type: One of "campaign", "keyword", "search_query", "geographic".
            date_range: A predefined range, e.g. "LastWeek", "LastMonth", "LastThreeMonths",
                "ThisYear", "LastYear".
            columns: Optional explicit column list; a sensible default is used per report type.
        """
        return guarded(
            lambda: reporting.run_performance_report(
                get_client(),
                report_type=report_type,
                date_range=date_range,
                columns=columns,
            )
        )
