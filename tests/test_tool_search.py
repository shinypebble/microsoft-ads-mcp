"""TOOL_SEARCH collapses the catalog behind BM25 search while preserving the READ_ONLY gate."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp import Client

from microsoft_ads_mcp.config import Settings
from microsoft_ads_mcp.server import _PINNED_TOOLS, create_server

_BASE = dict(developer_token="d", client_id="c", refresh_token="r", account_id="1")


def _listed(settings: Settings) -> set[str]:
    server = create_server(settings)
    return {t.name for t in asyncio.run(server.list_tools())}


def _search(settings: Settings, query: str) -> str:
    """Run the synthetic search_tools and return its result serialized to a string."""

    async def run() -> Any:
        async with Client(create_server(settings)) as client:
            res = await client.call_tool("search_tools", {"query": query})
            return getattr(res, "data", None) or getattr(res, "structured_content", None) or res

    return json.dumps(asyncio.run(run()), default=str)


def test_default_off_lists_full_catalog() -> None:
    names = _listed(Settings(**_BASE, read_only=False, tool_search=False))
    assert "search_tools" not in names  # no synthetic tools
    assert {"update_campaign", "get_campaigns"} <= names  # real tools listed directly


def test_on_collapses_to_pinned_plus_meta() -> None:
    names = _listed(Settings(**_BASE, read_only=False, tool_search=True))
    assert names == set(_PINNED_TOOLS) | {"search_tools", "call_tool"}
    assert "update_campaign" not in names  # write tools hidden from the listing
    assert "get_ads" not in names  # non-pinned read tools hidden too


def test_search_discovers_hidden_tool() -> None:
    found = _search(Settings(**_BASE, read_only=False, tool_search=True), "update a campaign name")
    assert "update_campaign" in found  # reachable via search even though it's not listed


def test_read_only_hides_write_tools_from_search() -> None:
    # Write tools aren't registered under READ_ONLY, so search (which runs through the full
    # pipeline) cannot surface them — the gate holds even with discovery on.
    found = _search(Settings(**_BASE, read_only=True, tool_search=True), "update a campaign name")
    assert "update_campaign" not in found
