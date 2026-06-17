"""Config loads from the environment with the expected aliases and defaults."""

from __future__ import annotations

import pytest

from microsoft_ads_mcp.config import Settings


def test_defaults_have_no_credentials() -> None:
    s = Settings()
    assert s.has_credentials is False
    assert s.read_only is False
    assert s.environment == "production"
    assert s.mcp_transport == "stdio"


def test_reads_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MICROSOFT_ADS_DEVELOPER_TOKEN", "dev")
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_ID", "cid")
    monkeypatch.setenv("READ_ONLY", "true")
    s = Settings()
    assert s.developer_token == "dev"
    assert s.client_id == "cid"
    assert s.has_credentials is True
    assert s.read_only is True


def test_token_path_under_home() -> None:
    s = Settings()
    assert s.token_path.name == "tokens.json"
    assert "microsoft-ads" in str(s.token_path)
