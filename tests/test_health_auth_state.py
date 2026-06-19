"""account_health maps auth failures to a discriminated auth_state (issue 2)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastmcp import FastMCP

from microsoft_ads_mcp.api.errors import InvalidCredentialsError, MsAdsApiError
from microsoft_ads_mcp.tools import health
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


def _run_account_health(monkeypatch: pytest.MonkeyPatch, client: object, settings: object):
    """Register account_health with stubbed client/get_user and return its AccountHealth."""
    monkeypatch.setattr(health, "get_client", lambda: client)
    monkeypatch.setattr(health, "get_user", lambda _client: SimpleNamespace(user_name="Tester"))
    mcp = FastMCP("test")
    health.register(mcp, settings)
    tool = asyncio.run(mcp.get_tool("account_health"))
    return tool.fn()


def test_health_reports_live_client_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    # account_health must report the *live* client scope so it reflects set_active_account,
    # not the static config. Here the client points at a switched account/customer while the
    # settings still hold the originals; account_health must follow the client (issue 9).
    client = SimpleNamespace(account_id="999", customer_id="555")
    settings = SimpleNamespace(
        read_only=False, environment="production", account_id="123", customer_id="111"
    )
    result = _run_account_health(monkeypatch, client, settings)
    assert result.ok and result.account_id == "999" and result.customer_id == "555"


def test_health_customer_id_none_is_null_not_string(monkeypatch: pytest.MonkeyPatch) -> None:
    # A missing customer id must serialize as null, never the literal string "None".
    client = SimpleNamespace(account_id="123", customer_id=None)
    settings = SimpleNamespace(
        read_only=True, environment="production", account_id="123", customer_id=None
    )
    result = _run_account_health(monkeypatch, client, settings)
    assert result.account_id == "123" and result.customer_id is None
