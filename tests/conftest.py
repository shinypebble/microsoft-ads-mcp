"""Shared fixtures. Tests avoid network: they construct settings and inspect registration."""

from __future__ import annotations

import pytest

from microsoft_ads_mcp.config import Settings


@pytest.fixture
def writable_settings() -> Settings:
    return Settings(
        developer_token="dev-token",
        client_id="client-id",
        refresh_token="refresh-token",
        account_id="123",
        read_only=False,
    )


@pytest.fixture
def readonly_settings() -> Settings:
    return Settings(
        developer_token="dev-token",
        client_id="client-id",
        refresh_token="refresh-token",
        account_id="123",
        read_only=True,
    )
