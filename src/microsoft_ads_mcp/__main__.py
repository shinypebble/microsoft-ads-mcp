"""Console entry point: ``python -m microsoft_ads_mcp`` (or the ``microsoft-ads-mcp`` script)."""

from __future__ import annotations

from .config import get_settings
from .server import mcp


def main() -> None:
    settings = get_settings()
    if settings.mcp_transport == "http":
        mcp.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
