"""Resolve ZIP / postal codes to Microsoft LocationIds via the geographical-locations file.

Location targeting takes a Microsoft ``LocationId``, not the ZIP string. The id->ZIP mapping
lives in a large account-agnostic CSV that Microsoft exposes through a temporary URL
(``get_geo_locations_file_url``). We download it once, cache it next to the token store, and
serve lookups from the cache -- re-downloading only when the cache is stale.
"""

from __future__ import annotations

import csv
import gzip
import io
import time
import zipfile
from pathlib import Path

import requests
from openapi_client.models.campaign.get_geo_locations_file_url_request import (
    GetGeoLocationsFileUrlRequest,
)

from ..api.client import CAMPAIGN, MsAdsClient
from ..api.errors import MsAdsApiError
from ..domain.entities import PostalCodeLocation
from . import first_attr

# The geo file changes rarely; refresh roughly monthly.
_GEO_VERSION = "2.0"
_MAX_AGE_SECONDS = 30 * 24 * 3600


def _cache_path(client: MsAdsClient, locale: str) -> Path:
    return client.settings.token_path.parent / "geo" / f"geo-{locale}.csv"


def _is_fresh(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < _MAX_AGE_SECONDS


def _download_geo_csv(client: MsAdsClient, locale: str) -> str:
    """Fetch the geo-locations file URL, download it, and return the decoded CSV text."""
    resp = client.call(
        CAMPAIGN,
        "get_geo_locations_file_url",
        GetGeoLocationsFileUrlRequest(version=_GEO_VERSION, language_locale=locale),
    )
    url = first_attr(resp, "FileUrl", "file_url")
    if not url:
        raise MsAdsApiError(0, "Microsoft did not return a geo-locations file URL")
    r = requests.get(str(url), timeout=180)
    r.raise_for_status()
    content = r.content
    if content[:2] == b"\x1f\x8b":  # gzip
        return gzip.decompress(content).decode("utf-8-sig")
    if content[:2] == b"PK":  # zip archive
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            name = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                raise MsAdsApiError(0, "Geo-locations archive contained no CSV")
            return zf.read(name).decode("utf-8-sig")
    return content.decode("utf-8-sig")


def _index_postal_codes(csv_text: str) -> dict[str, str]:
    """Build a ``{POSTAL_CODE -> LocationId}`` index from the geo CSV.

    The file's column layout can vary, so we locate columns by header name and index every
    "Postal Code"-type row by whichever code-bearing column is present, skipping rows marked
    ``PendingDeprecation``.
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = iter(reader)
    header = next(rows, None)
    if not header:
        return {}
    cols = {h.strip().lower(): i for i, h in enumerate(header)}

    def col(*names: str) -> int | None:
        for n in names:
            if n in cols:
                return cols[n]
        return None

    id_col = col("location id", "locationid")
    type_col = col("location type", "locationtype")
    status_col = col("status")
    code_cols = [c for c in (col("code"), col("postal code"), col("name")) if c is not None]
    if id_col is None or not code_cols:
        raise MsAdsApiError(0, "Unexpected geo-locations file format (missing id/code columns)")

    index: dict[str, str] = {}
    for row in rows:
        if len(row) <= id_col:
            continue
        if (
            type_col is not None
            and len(row) > type_col
            and row[type_col].strip().replace(" ", "").lower() != "postalcode"
        ):
            continue
        if (
            status_col is not None
            and len(row) > status_col
            and row[status_col].strip().lower() == "pendingdeprecation"
        ):
            continue
        loc_id = row[id_col].strip()
        for c in code_cols:
            if len(row) > c and row[c].strip():
                index.setdefault(row[c].strip().upper(), loc_id)
    return index


def resolve_postal_codes(
    client: MsAdsClient, *, postal_codes: list[str], language_locale: str = "en"
) -> list[PostalCodeLocation]:
    """Resolve ZIP / postal codes to Microsoft LocationIds (cached lookup)."""
    cache = _cache_path(client, language_locale)
    if _is_fresh(cache):
        text = cache.read_text(encoding="utf-8")
    else:
        text = _download_geo_csv(client, language_locale)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    index = _index_postal_codes(text)
    out: list[PostalCodeLocation] = []
    for code in postal_codes:
        loc_id = index.get(code.strip().upper())
        out.append(
            PostalCodeLocation(postal_code=code, location_id=loc_id, found=loc_id is not None)
        )
    return out
