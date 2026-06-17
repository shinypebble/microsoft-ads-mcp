"""The single point where Microsoft Advertising API calls are dispatched.

``MsAdsClient`` lazily builds an authenticated ``AuthorizationData`` and caches one
``ServiceClient`` per Bing Ads service. It is synchronous because the underlying ``msads`` SDK
is synchronous; FastMCP runs the (sync) tools in a worker thread, so nothing blocks the loop.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from bingads.service_client import ServiceClient

from ..config import Settings
from .auth import build_authorization_data
from .errors import translate

if TYPE_CHECKING:
    from bingads.authorization import AuthorizationData

T = TypeVar("T")

# Bing Ads service names (all version 13).
CAMPAIGN = "CampaignManagementService"
CUSTOMER = "CustomerManagementService"
REPORTING = "ReportingService"
BULK = "BulkService"
_API_VERSION = 13


class MsAdsClient:
    """Authenticated facade over the msads ServiceClients for a single configured account."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._auth: AuthorizationData | None = None
        self._services: dict[str, ServiceClient] = {}
        # Cached account/user metadata, populated by health/overview tools.
        self.account: dict[str, Any] | None = None

    @property
    def settings(self) -> Settings:
        return self._settings

    def authorization(self) -> AuthorizationData:
        """Return the cached ``AuthorizationData``, building (and authenticating) it once."""
        if self._auth is None:
            self._auth = build_authorization_data(self._settings)
        return self._auth

    @property
    def account_id(self) -> Any:
        return self.authorization().account_id

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

    def call(self, service_name: str, method: str, request: Any) -> Any:
        """Invoke ``method`` on ``service_name`` using the SDK's ``<method>_request=`` pattern.

        The REST SDK names every method's request kwarg as the method name plus ``_request``
        (e.g. ``add_campaigns(add_campaigns_request=...)``). Errors are translated.
        """
        svc = self.service(service_name)
        fn = getattr(svc, method)
        return self.execute(lambda: fn(**{f"{method}_request": request}))


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
