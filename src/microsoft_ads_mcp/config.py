"""Runtime configuration loaded from the environment (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings.

    Read from environment variables (case-insensitive) or a local ``.env`` file. The required
    values are the developer token and client id; a refresh token is needed to run
    non-interactively (otherwise mint one with the auth tools).

    Credentials are read from ``MICROSOFT_ADS_*`` env vars; ``READ_ONLY`` and the ``MCP_*``
    transport vars keep their conventional names (matched case-insensitively to the fields).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Microsoft Advertising credentials ---
    # Optional at load time so the package imports without secrets (e.g. in tests); the server
    # lifespan validates what it needs before serving.
    developer_token: str = Field(default="", validation_alias="MICROSOFT_ADS_DEVELOPER_TOKEN")
    client_id: str = Field(default="", validation_alias="MICROSOFT_ADS_CLIENT_ID")
    client_secret: str = Field(default="", validation_alias="MICROSOFT_ADS_CLIENT_SECRET")
    refresh_token: str = Field(default="", validation_alias="MICROSOFT_ADS_REFRESH_TOKEN")
    account_id: str = Field(default="", validation_alias="MICROSOFT_ADS_ACCOUNT_ID")
    customer_id: str = Field(default="", validation_alias="MICROSOFT_ADS_CUSTOMER_ID")
    environment: str = Field(default="production", validation_alias="MICROSOFT_ADS_ENVIRONMENT")

    # --- Write gate ---
    # Defaults to False: writes are enabled unless explicitly locked with READ_ONLY=true.
    read_only: bool = False

    # --- Transport (used by __main__) ---
    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000

    @property
    def token_path(self) -> Path:
        """Where minted/refreshed OAuth tokens are persisted (created mode 0600)."""
        return Path.home() / ".config" / "microsoft-ads" / "tokens.json"

    @property
    def has_credentials(self) -> bool:
        """True when the non-OAuth credentials needed to build a client are present."""
        return bool(self.developer_token and self.client_id)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (cached)."""
    return Settings()  # all fields have defaults; real values come from the environment
