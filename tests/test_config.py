"""Config loads from the environment with the expected aliases and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from microsoft_ads_mcp.config import Settings


def test_defaults_have_no_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermetic: point both dotenv sources at empty dirs -- chdir away from the project-local
    # `.env`, and HOME at a clean tmp so `~/.config/microsoft-ads/.env` resolves to nothing --
    # with no exported MICROSOFT_ADS_* vars, so this asserts true defaults, not ambient state.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("MICROSOFT_ADS_DEVELOPER_TOKEN", "MICROSOFT_ADS_CLIENT_ID", "READ_ONLY"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.has_credentials is False
    assert s.read_only is False
    assert s.environment == "production"
    assert s.mcp_transport == "stdio"


def test_reads_user_config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The `uvx microsoft-ads-mcp` story: no project-local `.env`, secrets live only in the
    # cwd-independent `~/.config/microsoft-ads/.env`. Settings should still find them.
    home = tmp_path / "home"
    cfg = home / ".config" / "microsoft-ads"
    cfg.mkdir(parents=True)
    (cfg / ".env").write_text(
        "MICROSOFT_ADS_DEVELOPER_TOKEN=devtok\nMICROSOFT_ADS_CLIENT_ID=clientid\n"
    )
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("HOME", str(home))
    for var in ("MICROSOFT_ADS_DEVELOPER_TOKEN", "MICROSOFT_ADS_CLIENT_ID"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.developer_token == "devtok"
    assert s.client_id == "clientid"
    assert s.has_credentials is True


def test_project_env_overrides_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A repo-local `.env` (development) wins over the cwd-independent user-config `.env`.
    home = tmp_path / "home"
    cfg = home / ".config" / "microsoft-ads"
    cfg.mkdir(parents=True)
    (cfg / ".env").write_text("MICROSOFT_ADS_CLIENT_ID=from-user-config\n")
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / ".env").write_text("MICROSOFT_ADS_CLIENT_ID=from-project\n")
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MICROSOFT_ADS_CLIENT_ID", raising=False)
    s = Settings()
    assert s.client_id == "from-project"


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
