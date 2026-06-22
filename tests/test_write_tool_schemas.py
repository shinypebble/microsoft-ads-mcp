"""Boundary tests for write-tool input schemas.

The service-layer tests in test_mutations.py call ``mutations.*`` directly, which bypasses the
FastMCP/Pydantic schema validation a real tool call goes through. These tests assert what the
*registered tool* actually accepts -- the boundary that an MCP client hits -- so a service contract
(e.g. ``_bidding_scheme`` normalizing the long-form discriminator) can't drift away from the schema
the model is validated against.
"""

from __future__ import annotations

import asyncio
from typing import Any, get_args

from microsoft_ads_mcp.config import Settings
from microsoft_ads_mcp.domain.entities import BidStrategyTypeInput
from microsoft_ads_mcp.server import create_server


def _writable() -> Settings:
    return Settings(
        developer_token="dev-token",
        client_id="client-id",
        refresh_token="refresh-token",
        account_id="123",
        read_only=False,
    )


def _param_enum(tool: Any, param: str) -> set[str]:
    """Pull the enum a tool's parameter validates against (direct enum or nested in anyOf)."""
    prop = tool.parameters["properties"][param]
    if "enum" in prop:
        return set(prop["enum"])
    for branch in prop.get("anyOf", []):
        if "enum" in branch:
            return set(branch["enum"])
    raise AssertionError(f"no enum found for parameter {param!r}: {prop!r}")


def _bid_strategy_enum(tool_name: str) -> set[str]:
    server = create_server(_writable())
    tool = asyncio.run(server.get_tool(tool_name))
    return _param_enum(tool, "bid_strategy_type")


def test_update_campaign_admits_long_form_bid_strategies() -> None:
    # The round-trip the docstrings promise: a value read from get_campaigns (which reports the long
    # "TargetRoasBiddingScheme" / "MaxConversionValueBiddingScheme" discriminator for those two
    # strategies) must pass the tool's schema validation, not be rejected before _bidding_scheme can
    # normalize it.
    enum = _bid_strategy_enum("update_campaign")
    assert "TargetRoasBiddingScheme" in enum
    assert "MaxConversionValueBiddingScheme" in enum


def test_create_campaign_admits_long_form_bid_strategies() -> None:
    enum = _bid_strategy_enum("create_campaign")
    assert "TargetRoasBiddingScheme" in enum
    assert "MaxConversionValueBiddingScheme" in enum


def test_bid_strategy_schema_matches_input_literal() -> None:
    # The schema the model is validated against is exactly BidStrategyTypeInput -- guards both
    # directions: the long forms stay admitted, and no stray value sneaks in.
    expected = set(get_args(BidStrategyTypeInput))
    assert _bid_strategy_enum("update_campaign") == expected
    assert _bid_strategy_enum("create_campaign") == expected
