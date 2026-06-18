"""account_health maps auth failures to a discriminated auth_state (issue 2)."""

from __future__ import annotations

from types import SimpleNamespace

from microsoft_ads_mcp.api.errors import InvalidCredentialsError, MsAdsApiError
from microsoft_ads_mcp.tools.health import _classify_auth_error

# A stand-in settings object with a dev token present (decoupled from any .env on disk).
_OK = SimpleNamespace(developer_token="dev")


def test_no_dev_token() -> None:
    settings = SimpleNamespace(developer_token="")
    state, needs = _classify_auth_error(settings, InvalidCredentialsError(0, "anything"))
    assert state == "dev_token_missing" and needs is False


def test_no_refresh_token_prompts_interactive() -> None:
    state, needs = _classify_auth_error(
        _OK, InvalidCredentialsError(0, "No refresh token. Set MICROSOFT_ADS_REFRESH_TOKEN")
    )
    assert state == "no_token" and needs is True


def test_expired_token_prompts_interactive() -> None:
    state, needs = _classify_auth_error(
        _OK, InvalidCredentialsError(401, "The OAuth token has expired")
    )
    assert state == "token_expired" and needs is True


def test_rejected_credential_does_not_auto_prompt() -> None:
    # A 401/403 is a credential rejection (token_rejected) even though Microsoft's generic
    # message literally says "...or the account is inactive". We must NOT auto-advise re-auth:
    # re-consent could clobber a shared token, which is what made the original issue worse.
    state, needs = _classify_auth_error(
        _OK, InvalidCredentialsError(401, "invalid or the account is inactive")
    )
    assert state == "token_rejected" and needs is False


def test_generic_rejected() -> None:
    state, needs = _classify_auth_error(_OK, InvalidCredentialsError(403, "forbidden"))
    assert state == "token_rejected" and needs is False


def test_non_credential_inactive_account() -> None:
    # A non-auth API error mentioning inactivity is an account problem, not a token problem.
    state, needs = _classify_auth_error(_OK, MsAdsApiError(400, "account is not active"))
    assert state == "account_inactive" and needs is False
