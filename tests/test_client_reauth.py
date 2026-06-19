"""The client self-heals a stale cached credential (issue 9 follow-up).

A long-running server caches its ``AuthorizationData``; if that access token's refresh later
fails, every call stays wedged on a credential error until the process restarts. ``call`` drops
the stale cache and retries once -- but only when there *was* a cached credential, so a genuinely
bad token is not retried into a pointless double round-trip.
"""

from __future__ import annotations

from typing import Any

import pytest

from microsoft_ads_mcp.api.client import CUSTOMER, MsAdsClient
from microsoft_ads_mcp.api.errors import InvalidCredentialsError, MsAdsApiError
from microsoft_ads_mcp.config import Settings

_SETTINGS = Settings(
    developer_token="dev", client_id="cid", refresh_token="refresh", account_id="123"
)


class _FakeService:
    """A service whose method fails the first N times with a credential error, then succeeds."""

    def __init__(self, fail_times: int, counter: dict[str, int]) -> None:
        self._fail_times = fail_times
        self._counter = counter

    def get_user(self, **_kwargs: Any) -> str:
        self._counter["calls"] += 1
        if self._counter["calls"] <= self._fail_times:
            raise InvalidCredentialsError(105, "credentials invalid or the account is inactive")
        return "ok"


def _wire(
    monkeypatch: pytest.MonkeyPatch, client: MsAdsClient, counter: dict[str, int], fail_times: int
) -> dict[str, int]:
    """Stub service() (no SDK/network) and count how often the auth cache is reset."""
    monkeypatch.setattr(client, "service", lambda _name: _FakeService(fail_times, counter))
    resets = {"n": 0}
    real_reset = client._reset_auth

    def tracked() -> None:
        resets["n"] += 1
        real_reset()

    monkeypatch.setattr(client, "_reset_auth", tracked)
    return resets


def test_call_self_heals_when_cached_credential_goes_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MsAdsClient(_SETTINGS)
    client._auth = object()  # pretend a credential was already built and cached
    counter = {"calls": 0}
    resets = _wire(monkeypatch, client, counter, fail_times=1)

    result = client.call(CUSTOMER, "get_user", object())

    assert result == "ok"
    assert counter["calls"] == 2  # failed once, retried once
    assert resets["n"] == 1  # the stale cache was dropped before the retry
    assert client._auth is None  # and left cleared for a fresh rebuild


def test_call_does_not_retry_without_cached_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MsAdsClient(_SETTINGS)
    client._auth = None  # nothing cached: a fresh build that fails won't change on retry
    counter = {"calls": 0}
    resets = _wire(monkeypatch, client, counter, fail_times=99)

    with pytest.raises(InvalidCredentialsError):
        client.call(CUSTOMER, "get_user", object())

    assert counter["calls"] == 1  # no retry
    assert resets["n"] == 0


def test_call_retries_only_once_then_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MsAdsClient(_SETTINGS)
    client._auth = object()
    counter = {"calls": 0}
    resets = _wire(monkeypatch, client, counter, fail_times=99)  # never recovers

    with pytest.raises(InvalidCredentialsError):
        client.call(CUSTOMER, "get_user", object())

    assert counter["calls"] == 2  # original + exactly one retry, no infinite loop
    assert resets["n"] == 1


class _BadRequestService:
    def __init__(self, counter: dict[str, int]) -> None:
        self._counter = counter

    def get_user(self, **_kwargs: Any) -> Any:
        self._counter["calls"] += 1
        raise MsAdsApiError(400, "bad request")


def test_call_does_not_retry_non_credential_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MsAdsClient(_SETTINGS)
    client._auth = object()
    counter = {"calls": 0}
    resets = {"n": 0}
    real_reset = client._reset_auth

    def tracked() -> None:
        resets["n"] += 1
        real_reset()

    monkeypatch.setattr(client, "_reset_auth", tracked)
    monkeypatch.setattr(client, "service", lambda _name: _BadRequestService(counter))

    with pytest.raises(MsAdsApiError) as exc:
        client.call(CUSTOMER, "get_user", object())

    assert exc.value.status == 400
    assert counter["calls"] == 1  # a non-auth error must not trigger a reauth retry
    assert resets["n"] == 0


class _FakeAuth:
    """Stand-in for AuthorizationData carrying just the scope fields a rebuild sets."""

    def __init__(self, account_id: str | None = None, customer_id: str | None = None) -> None:
        self.account_id = account_id
        self.customer_id = customer_id


def test_call_preserves_active_account_across_auth_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A rebuild always returns the *configured* (default) scope; the session override must win.
    monkeypatch.setattr(
        "microsoft_ads_mcp.api.client.build_authorization_data",
        lambda _settings: _FakeAuth(account_id="123", customer_id="000"),
    )
    client = MsAdsClient(_SETTINGS)
    client.set_account("999", "555")  # rescope this session to a non-default account
    assert client.account_id == "999"
    assert client.customer_id == "555"

    counter = {"calls": 0}
    resets = _wire(monkeypatch, client, counter, fail_times=1)  # one credential hiccup, then ok

    result = client.call(CUSTOMER, "get_user", object())

    assert result == "ok"
    assert resets["n"] == 1  # the stale credential was dropped and rebuilt
    # The self-heal rebuilt from the default scope but must reapply the session override,
    # not silently revert to the configured account.
    assert client.account_id == "999"
    assert client.customer_id == "555"
