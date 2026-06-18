"""OAuth authentication flow and a permission-hardened token store.

The Microsoft Advertising API uses OAuth: an OAuth app (client id) for the account's identity
provider -- Microsoft (Azure) by default, or Google for Google-federated accounts -- plus a
developer token, exchanged for a long-lived refresh token. We persist the refresh token so the
server can run non-interactively across restarts, and we mint one interactively via the auth
tools when none is configured.
"""

from __future__ import annotations

import json
import os
from typing import Any

from bingads.authorization import (
    AuthorizationData,
    GoogleOAuthDesktopMobileAuthCodeGrant,
    OAuthDesktopMobileAuthCodeGrant,
    OAuthWebAuthCodeGrant,
)

from ..config import Settings
from .errors import InvalidCredentialsError, translate

# Native-client redirect used by desktop/mobile app registrations.
_NATIVE_REDIRECT = "https://login.microsoftonline.com/common/oauth2/nativeclient"


def load_tokens(settings: Settings) -> dict[str, Any]:
    """Read the persisted token blob, or an empty dict if none exists yet."""
    path = settings.token_path
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except OSError, ValueError:
        return {}


def save_tokens(settings: Settings, tokens: dict[str, Any]) -> None:
    """Persist tokens to disk with owner-only (0600) permissions.

    Hardening the file mode addresses the original server's world-readable refresh token: the
    refresh token is a long-lived credential to the ad account.
    """
    path = settings.token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the start (umask-independent), then write.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tokens, f, indent=2)
    os.chmod(path, 0o600)  # enforce mode even if the file pre-existed


def make_grant(
    settings: Settings,
) -> (
    GoogleOAuthDesktopMobileAuthCodeGrant | OAuthDesktopMobileAuthCodeGrant | OAuthWebAuthCodeGrant
):
    """Construct the right OAuth grant for the configured identity provider.

    Google-federated accounts (``identity_provider="google"``) must authenticate through
    Google's OAuth endpoints; the SDK's Google grant exchanges a Google access token and the
    REST API resolves the identity from it (no extra header). For Microsoft accounts, a client
    secret implies a web (confidential) app; otherwise a desktop/native app.
    """
    if not settings.client_id:
        raise InvalidCredentialsError(0, "MICROSOFT_ADS_CLIENT_ID is not set")

    provider = settings.identity_provider.strip().lower()
    if provider == "google":
        return GoogleOAuthDesktopMobileAuthCodeGrant(
            client_id=settings.client_id,
            client_secret=settings.client_secret or None,
            env=settings.environment,
        )
    if provider != "microsoft":
        raise InvalidCredentialsError(
            0, f"MICROSOFT_ADS_IDENTITY_PROVIDER must be 'microsoft' or 'google', got {provider!r}"
        )
    if settings.client_secret:
        return OAuthWebAuthCodeGrant(
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            redirection_uri=_NATIVE_REDIRECT,
            env=settings.environment,
        )
    return OAuthDesktopMobileAuthCodeGrant(client_id=settings.client_id, env=settings.environment)


def authorization_url(settings: Settings) -> str:
    """The URL the user opens to sign in and authorize the app."""
    return make_grant(settings).get_authorization_endpoint()


def complete_authorization(settings: Settings, redirect_url: str) -> str:
    """Exchange the post-login redirect URL for tokens; persist the refresh token.

    Returns the refresh token (also written to the token store).
    """
    grant = make_grant(settings)
    try:
        grant.request_oauth_tokens_by_response_uri(redirect_url)
    except Exception as exc:
        raise translate(exc) from exc
    refresh = grant.oauth_tokens.refresh_token
    tokens = load_tokens(settings)
    tokens["refresh_token"] = refresh
    save_tokens(settings, tokens)
    return refresh


def build_authorization_data(settings: Settings) -> AuthorizationData:
    """Build an authenticated ``AuthorizationData`` for ServiceClient construction.

    Resolves the refresh token from settings or the token store, exchanges it for an access
    token, and persists any rotated refresh token. Raises ``InvalidCredentialsError`` when no
    refresh token is available (the caller should direct the user through the auth tools).
    """
    if not settings.developer_token:
        raise InvalidCredentialsError(0, "MICROSOFT_ADS_DEVELOPER_TOKEN is not set")

    tokens = load_tokens(settings)
    refresh = settings.refresh_token or tokens.get("refresh_token")
    if not refresh:
        raise InvalidCredentialsError(
            0,
            "No refresh token. Set MICROSOFT_ADS_REFRESH_TOKEN, or run get_auth_url then "
            "complete_auth to mint one.",
        )

    grant = make_grant(settings)
    try:
        grant.request_oauth_tokens_by_refresh_token(refresh)
    except Exception as exc:
        raise translate(exc) from exc

    # Persist a rotated refresh token if the provider issued a new one.
    rotated = grant.oauth_tokens.refresh_token
    if rotated and rotated != tokens.get("refresh_token"):
        save_tokens(settings, {**tokens, "refresh_token": rotated})

    return AuthorizationData(
        account_id=settings.account_id or tokens.get("account_id"),
        customer_id=settings.customer_id or tokens.get("customer_id"),
        developer_token=settings.developer_token,
        authentication=grant,
    )
