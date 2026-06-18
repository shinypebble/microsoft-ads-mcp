"""Config loads from the environment with the expected aliases and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from microsoft_ads_mcp.config import Settings


def test_defaults_have_no_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermetic: run where there is no .env (the project root has a real one) and with no
    # exported MICROSOFT_ADS_* vars, so this asserts true defaults rather than ambient state.
    monkeypatch.chdir(tmp_path)
    for var in ("MICROSOFT_ADS_DEVELOPER_TOKEN", "MICROSOFT_ADS_CLIENT_ID", "READ_ONLY"):
        monkeypatch.delenv(var, raising=False)
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
