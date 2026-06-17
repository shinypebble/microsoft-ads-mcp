"""Error translation: SDK exceptions collapse into the right normalized types."""

from __future__ import annotations

from openapi_client.exceptions import ApiException

from microsoft_ads_mcp.api.errors import (
    InvalidCredentialsError,
    MsAdsApiError,
    translate,
)


def test_passthrough_already_translated() -> None:
    err = MsAdsApiError(400, "boom")
    assert translate(err) is err


def test_401_becomes_invalid_credentials() -> None:
    exc = ApiException(status=401, reason="Unauthorized")
    exc.body = '{"error": {"message": "bad token"}}'
    out = translate(exc)
    assert isinstance(out, InvalidCredentialsError)
    assert out.status == 401
    assert out.message == "bad token"


def test_400_extracts_errors_array_message() -> None:
    exc = ApiException(status=400, reason="Bad Request")
    exc.body = '{"Errors": [{"Code": 123, "Message": "invalid budget"}]}'
    out = translate(exc)
    assert isinstance(out, MsAdsApiError)
    assert not isinstance(out, InvalidCredentialsError)
    assert out.status == 400
    assert "invalid budget" in out.message


def test_oauth_named_exception_is_credentials() -> None:
    class OAuthTokenRequestException(Exception):
        pass

    out = translate(OAuthTokenRequestException("refresh failed"))
    assert isinstance(out, InvalidCredentialsError)
