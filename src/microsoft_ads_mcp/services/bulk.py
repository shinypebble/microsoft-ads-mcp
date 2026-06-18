"""Bulk API flows: export the account to a Bulk file, and apply Bulk entity records.

Both are asynchronous: submit, then poll a status endpoint to completion -- the same shape as
the reporting flow. Downloads return the result file URL (the Bulk CSV/zip can be large, so we
hand back the URL rather than inlining it); uploads accept ready-made Bulk CSV rows and report
the per-request status and result URL.
"""

from __future__ import annotations

import time
from typing import Any

from openapi_client.models.bulk.download_campaigns_by_account_ids_request import (
    DownloadCampaignsByAccountIdsRequest,
)
from openapi_client.models.bulk.download_entity import DownloadEntity
from openapi_client.models.bulk.get_bulk_download_status_request import (
    GetBulkDownloadStatusRequest,
)
from openapi_client.models.bulk.get_bulk_upload_status_request import GetBulkUploadStatusRequest
from openapi_client.models.bulk.upload_entity_records_request import UploadEntityRecordsRequest

from ..api.client import BULK, MsAdsClient
from ..api.errors import MsAdsApiError
from . import as_list, first_attr

_DEFAULT_ENTITIES = ["Campaigns", "AdGroups", "Ads", "Keywords"]
_TERMINAL_OK = "Completed"
_TERMINAL_BAD = ("Failed", "FailedFullSyncRequired")


def _download_entities(names: list[str] | None) -> list[DownloadEntity]:
    """Map friendly entity names (e.g. "Campaigns") to DownloadEntity members."""
    chosen = names or _DEFAULT_ENTITIES

    def norm(s: str) -> str:
        return s.upper().replace("_", "").replace(" ", "")

    out: list[DownloadEntity] = []
    for name in chosen:
        target = norm(name)
        member = next(
            (m for m in DownloadEntity if m.name != "NONE" and norm(m.name) == target), None
        )
        if member is None:
            raise ValueError(f"unknown download entity {name!r}")
        out.append(member)
    return out


def _errors(resp: Any) -> list[str]:
    out: list[str] = []
    for err in as_list(first_attr(resp, "Errors", "errors")):
        msg = first_attr(err, "Message", "message", default="")
        code = first_attr(err, "Code", "code", "ErrorCode", "error_code", default="")
        out.append(f"{code}: {msg}".strip(": "))
    return out


def bulk_download(
    client: MsAdsClient,
    *,
    entities: list[str] | None = None,
    poll_interval_seconds: float = 5.0,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Export the configured account to a Bulk file and return the result file URL."""
    submit = client.call(
        BULK,
        "download_campaigns_by_account_ids",
        DownloadCampaignsByAccountIdsRequest(
            account_ids=[client.account_id],
            download_entities=_download_entities(entities),
            data_scope="EntityData",
            download_file_type="Csv",
            compression_type="Zip",
            format_version="6.0",
        ),
    )
    request_id = first_attr(submit, "DownloadRequestId", "download_request_id")
    if not request_id:
        raise MsAdsApiError(0, "Bulk download did not return a request id")
    status, url, errors = _poll(
        client,
        "get_bulk_download_status",
        GetBulkDownloadStatusRequest(request_id=request_id),
        poll_interval_seconds,
        timeout_seconds,
    )
    return {
        "request_id": str(request_id),
        "status": status,
        "result_file_url": url,
        "errors": errors,
    }


def bulk_upload(
    client: MsAdsClient,
    *,
    entity_records: list[str],
    poll_interval_seconds: float = 5.0,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Apply ready-made Bulk CSV rows to the account; poll to completion.

    ``entity_records`` are Bulk-file CSV rows (including the ``Format Version`` / ``Type`` header
    rows Microsoft expects). Returns the request status and the result file URL to inspect
    per-row outcomes.
    """
    submit = client.call(
        BULK,
        "upload_entity_records",
        UploadEntityRecordsRequest(
            entity_records=entity_records,
            response_mode="ErrorsAndResults",
            account_id=str(client.account_id),
        ),
    )
    request_id = first_attr(submit, "RequestId", "request_id")
    status = first_attr(submit, "RequestStatus", "request_status")
    errors = _errors(submit)
    url = None
    if request_id and status not in (_TERMINAL_OK, *_TERMINAL_BAD):
        status, url, errors = _poll(
            client,
            "get_bulk_upload_status",
            GetBulkUploadStatusRequest(request_id=request_id),
            poll_interval_seconds,
            timeout_seconds,
        )
    return {
        "request_id": str(request_id) if request_id else None,
        "status": status,
        "result_file_url": url,
        "errors": errors,
    }


def _poll(
    client: MsAdsClient, method: str, request: Any, interval: float, timeout: float
) -> tuple[str | None, str | None, list[str]]:
    """Poll a Bulk status endpoint until terminal; return (status, result_url, errors)."""
    deadline = time.monotonic() + timeout
    while True:
        resp = client.call(BULK, method, request)
        status = first_attr(resp, "RequestStatus", "request_status")
        if status == _TERMINAL_OK or (status and status.startswith("Completed")):
            url = first_attr(resp, "ResultFileUrl", "result_file_url")
            return str(status), str(url) if url else None, _errors(resp)
        if status in _TERMINAL_BAD:
            return str(status), None, _errors(resp)
        if time.monotonic() >= deadline:
            raise MsAdsApiError(
                0, f"Bulk request not done after {timeout:g}s (last status: {status})"
            )
        time.sleep(interval)
