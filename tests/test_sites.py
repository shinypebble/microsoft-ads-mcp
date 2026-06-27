"""Website-exclusion flows are read-modify-write over a campaign's negative-site list.

``SetNegativeSitesToCampaigns`` replaces the whole list, so ``add`` must read the current sites and
merge (never clobber) and ``remove`` must read then re-set the filtered list. These tests script
the GET response and SET response separately and assert the merged/filtered list that gets sent.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from microsoft_ads_mcp.services import sites

CID = "487928625"


class _FakeClient:
    account_id = "123"

    def __init__(self, *, current: list[str] | None = None, set_errors: list[Any] | None = None):
        self._current = list(current or [])
        self._set_errors = list(set_errors or [])
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        if method == "get_negative_sites_by_campaign_ids":
            return SimpleNamespace(
                campaign_negative_sites=[
                    SimpleNamespace(campaign_id=CID, negative_sites=list(self._current))
                ]
            )
        if method == "set_negative_sites_to_campaigns":
            return SimpleNamespace(partial_errors=self._set_errors)
        raise AssertionError(f"unexpected method {method}")


def _methods(client: _FakeClient) -> list[str]:
    return [m for _, m, _ in client.calls]


def _set_sites(client: _FakeClient) -> list[str]:
    for _, method, request in client.calls:
        if method == "set_negative_sites_to_campaigns":
            return request.campaign_negative_sites[0].negative_sites
    raise AssertionError("no set call recorded")


def test_add_merges_dedupes_and_strips_scheme() -> None:
    client = _FakeClient(current=["existing.com"])
    result = sites.add_website_exclusions(
        client, campaign_id=CID, urls=["https://New.com", "existing.com", "new.com"]
    )
    # Read happens before the set (read-modify-write), and only one set is issued.
    assert _methods(client) == [
        "get_negative_sites_by_campaign_ids",
        "set_negative_sites_to_campaigns",
    ]
    # existing.com retained (additive), New.com added, case-dup new.com dropped, scheme stripped.
    assert _set_sites(client) == ["existing.com", "New.com"]
    assert result.ok and result.ids == ["New.com", "existing.com"]
    get_request = client.calls[0][2]
    assert get_request.campaign_ids == [CID]


def test_remove_filters_case_insensitive_and_keeps_rest() -> None:
    client = _FakeClient(current=["keep.com", "Drop.com", "also-keep.com"])
    result = sites.remove_website_exclusions(client, campaign_id=CID, urls=["drop.com"])
    assert _methods(client) == [
        "get_negative_sites_by_campaign_ids",
        "set_negative_sites_to_campaigns",
    ]
    assert _set_sites(client) == ["keep.com", "also-keep.com"]
    assert result.ok and result.ids == ["drop.com"]
    assert "Unblocked 1 site(s)" in result.message


def test_get_returns_summary_with_count() -> None:
    client = _FakeClient(current=["a.com", "b.com"])
    summary = sites.get_website_exclusions(client, campaign_id=CID)
    assert summary.urls == ["a.com", "b.com"]
    assert summary.count == 2 and summary.campaign_id == CID
    assert _methods(client) == ["get_negative_sites_by_campaign_ids"]


def test_get_empty_when_no_exclusions() -> None:
    client = _FakeClient(current=[])
    summary = sites.get_website_exclusions(client, campaign_id=CID)
    assert summary.urls == [] and summary.count == 0


def test_set_partial_error_surfaces_as_not_ok() -> None:
    # Microsoft rejects excluding its own sites; the flat PartialError must surface, not crash.
    client = _FakeClient(
        current=[],
        set_errors=[SimpleNamespace(code="CampaignServiceCannotExclude", message="msn cannot")],
    )
    result = sites.add_website_exclusions(client, campaign_id=CID, urls=["msn.com"])
    assert result.ok is False
    assert result.partial_errors == ["CampaignServiceCannotExclude: msn cannot"]
    assert result.ids == ["msn.com"]


def test_get_surfaces_partial_error_when_campaign_missing() -> None:
    # An invalid / inaccessible campaign id comes back as a PartialError with no entry; that must
    # raise, not silently report count=0 (which would read as "no sites blocked").
    class _ErrClient:
        account_id = "123"

        def call(self, service: str, method: str, request: Any) -> Any:
            assert method == "get_negative_sites_by_campaign_ids"
            err = SimpleNamespace(code="CampaignServiceInvalidCampaignId", message="bad id")
            return SimpleNamespace(campaign_negative_sites=[], partial_errors=[err])

    with pytest.raises(ValueError, match="CampaignServiceInvalidCampaignId"):
        sites.get_website_exclusions(_ErrClient(), campaign_id="999")


def test_add_empty_urls_rejected() -> None:
    client = _FakeClient(current=["x.com"])
    with pytest.raises(ValueError, match="non-empty site"):
        sites.add_website_exclusions(client, campaign_id=CID, urls=["  ", ""])
    # Nothing was sent -- no read, no clobbering set.
    assert client.calls == []


def test_remove_empty_urls_rejected() -> None:
    client = _FakeClient(current=["x.com"])
    with pytest.raises(ValueError, match="non-empty site"):
        sites.remove_website_exclusions(client, campaign_id=CID, urls=[""])
    assert client.calls == []
