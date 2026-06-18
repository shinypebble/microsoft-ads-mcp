"""make_grant selects the correct OAuth grant for the configured identity provider."""

from __future__ import annotations

import pytest
from bingads.authorization import (
    GoogleOAuthDesktopMobileAuthCodeGrant,
    OAuthDesktopMobileAuthCodeGrant,
    OAuthWebAuthCodeGrant,
)

from microsoft_ads_mcp.api import auth
from microsoft_ads_mcp.api.errors import InvalidCredentialsError
from microsoft_ads_mcp.config import Settings


def _settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity_provider: str = "microsoft",
    client_secret: str = "",
    client_id: str = "c",
) -> Settings:
    # Set the env vars directly: they outrank the project .env, so these stay hermetic
    # regardless of the developer's local config.
    monkeypatch.setenv("MICROSOFT_ADS_DEVELOPER_TOKEN", "d")
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_ID", client_id)
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_SECRET", client_secret)
    monkeypatch.setenv("MICROSOFT_ADS_IDENTITY_PROVIDER", identity_provider)
    return Settings()


def test_microsoft_desktop_when_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    grant = auth.make_grant(_settings(monkeypatch, identity_provider="microsoft"))
    assert isinstance(grant, OAuthDesktopMobileAuthCodeGrant)


def test_microsoft_web_when_secret_present(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, identity_provider="microsoft", client_secret="s")
    assert isinstance(auth.make_grant(settings), OAuthWebAuthCodeGrant)


def test_google_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    grant = auth.make_grant(_settings(monkeypatch, identity_provider="google"))
    assert isinstance(grant, GoogleOAuthDesktopMobileAuthCodeGrant)


def test_google_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    grant = auth.make_grant(_settings(monkeypatch, identity_provider="Google"))
    assert isinstance(grant, GoogleOAuthDesktopMobileAuthCodeGrant)


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(InvalidCredentialsError):
        auth.make_grant(_settings(monkeypatch, identity_provider="bogus"))


def test_missing_client_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(InvalidCredentialsError):
        auth.make_grant(_settings(monkeypatch, identity_provider="google", client_id=""))
