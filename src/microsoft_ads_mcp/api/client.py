"""The single point where Microsoft Advertising API calls are dispatched.

``MsAdsClient`` lazily builds an authenticated ``AuthorizationData`` and caches one
``ServiceClient`` per Bing Ads service. It is synchronous because the underlying ``msads`` SDK
is synchronous; FastMCP runs the (sync) tools in a worker thread, so nothing blocks the loop.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from bingads.service_client import ServiceClient
from openapi_client.exceptions import ApiException

from ..config import Settings
from .auth import build_authorization_data
from .errors import InvalidCredentialsError, translate

if TYPE_CHECKING:
    from bingads.authorization import AuthorizationData

T = TypeVar("T")

# Bing Ads service names (all version 13).
CAMPAIGN = "CampaignManagementService"
CUSTOMER = "CustomerManagementService"
REPORTING = "ReportingService"
BULK = "BulkService"
AD_INSIGHT = "AdInsightService"
_API_VERSION = 13


class MsAdsClient:
    """Authenticated facade over the msads ServiceClients for a single configured account."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._auth: AuthorizationData | None = None
        self._services: dict[str, ServiceClient] = {}
        # Cached account/user metadata, populated by health/overview tools.
        self.account: dict[str, Any] | None = None
        # Session scope from set_active_account. Held separately from the cached
        # AuthorizationData so it survives an auth reset (see _reset_auth).
        self._account_override: str | None = None
        self._customer_override: str | None = None

    @property
    def settings(self) -> Settings:
        return self._settings

    def authorization(self) -> AuthorizationData:
        """Return the cached ``AuthorizationData``, building (and authenticating) it once.

        Reapplies any session scope from ``set_account`` after a (re)build so a credential
        reset never silently reverts to the configured account (see ``_reset_auth``).
        """
        if self._auth is None:
            self._auth = build_authorization_data(self._settings)
            if self._account_override is not None:
                self._auth.account_id = self._account_override
            if self._customer_override is not None:
                self._auth.customer_id = self._customer_override
        return self._auth

    @property
    def account_id(self) -> Any:
        return self.authorization().account_id

    @property
    def customer_id(self) -> Any:
        return self.authorization().customer_id

    def set_account(self, account_id: str, customer_id: str | None = None) -> None:
        """Switch the active account (and optionally customer) for subsequent calls.

        Records the scope as a session override (so it survives an auth reset), mutates the
        cached ``AuthorizationData`` in place, and drops the per-service client cache so the
        next call binds to the new scope. The OAuth credential is unchanged.
        """
        self._account_override = account_id
        if customer_id is not None:
            self._customer_override = customer_id
        auth = self.authorization()
        auth.account_id = account_id
        if customer_id is not None:
            auth.customer_id = customer_id
        self._services.clear()

    def _reset_auth(self) -> None:
        """Drop the cached credential and service clients so the next call re-authenticates.

        A long-running server caches its ``AuthorizationData`` (and the access token in its
        grant) for the life of the process. If that access token's refresh later fails or the
        grant goes stale, every subsequent call stays wedged on a credential error even though
        the persisted refresh token is still valid. Clearing the cache lets the next call rebuild
        from the currently persisted token, so the server self-heals instead of needing a restart.

        Only the credential is dropped: the session scope from ``set_account`` is kept (on
        ``_account_override``/``_customer_override``) and reapplied by ``authorization`` on the
        rebuild, so a reauth never reverts to the configured account.
        """
        self._auth = None
        self._services.clear()

    def service(self, name: str) -> ServiceClient:
        """Return a cached ServiceClient for ``name`` (e.g. ``CAMPAIGN``)."""
        svc = self._services.get(name)
        if svc is None:
            svc = ServiceClient(
                service=name,
                version=_API_VERSION,
                authorization_data=self.authorization(),
                environment=self._settings.environment,
            )
            self._services[name] = svc
        return svc

    def execute(self, fn: Callable[[], T]) -> T:
        """Run an SDK call, translating any SDK/transport exception into ``MsAdsApiError``."""
        try:
            return fn()
        except Exception as exc:
            raise translate(exc) from exc

    def _execute_with_auth_retry(self, op: Callable[[], T]) -> T:
        """Run ``op``, self-healing a stale cached credential exactly once.

        If the call is rejected for auth reasons *and* we were running off a previously-built
        credential, the cache is dropped and the call retried once against a freshly rebuilt one.
        A failure with no cached credential (a genuinely bad token) is not retried -- a rebuild
        would only reproduce it.
        """
        had_cached_auth = self._auth is not None
        try:
            return self.execute(op)
        except InvalidCredentialsError:
            if not had_cached_auth:
                raise
            self._reset_auth()
            return self.execute(op)

    def call(self, service_name: str, method: str, request: Any) -> Any:
        """Invoke ``method`` on ``service_name`` using the SDK's ``<method>_request=`` pattern.

        The REST SDK names every method's request kwarg as the method name plus ``_request``
        (e.g. ``add_campaigns(add_campaigns_request=...)``). Errors are translated, and a stale
        cached credential self-heals (see ``_execute_with_auth_retry``).
        """

        def op() -> Any:
            svc = self.service(service_name)
            fn = getattr(svc, method)
            return fn(**{f"{method}_request": request})

        return self._execute_with_auth_retry(op)

    def call_raw(self, service_name: str, method: str, request: Any) -> dict[str, Any]:
        """Like ``call`` but decode the JSON body directly, bypassing typed deserialization.

        Some Add* responses type their returned-id list as non-nullable strings, yet Microsoft
        returns a ``null`` id (with the reason in ``PartialErrors``) when an item is rejected --
        the typed model then fails to parse and the real error is lost behind a deserialization
        crash. Reading the raw body via the SDK's ``*_without_preload_content`` variant lets those
        partial errors surface as a clean result instead. Returns the decoded JSON dict (Pascal
        keys, as Microsoft sends them); ``first_attr`` reads it the same as a typed response.
        """

        def op() -> dict[str, Any]:
            svc = self.service(service_name)
            fn = getattr(svc, f"{method}_without_preload_content")
            resp = fn(**{f"{method}_request": request})
            status = int(getattr(resp, "status", 0) or 0)
            raw = resp.data
            if status >= 400:
                # Re-raise as the SDK's typed exception so translate() (and the auth self-heal)
                # treat it like any other HTTP error.
                ApiException.from_response(http_resp=resp, body=None, data=None)
            text = raw.decode("utf-8") if isinstance(raw, bytes | bytearray) else raw
            return json.loads(text) if text else {}

        return self._execute_with_auth_retry(op)


# ----------------------------------------------------------------- module singleton

_client: MsAdsClient | None = None


def set_client(client: MsAdsClient | None) -> None:
    """Install (or clear) the process-wide client used by tools."""
    global _client
    _client = client


def get_client() -> MsAdsClient:
    """Return the installed client, or raise if the server lifespan hasn't run."""
    if _client is None:
        raise RuntimeError("MsAdsClient is not initialized; the server lifespan must run first.")
    return _client
