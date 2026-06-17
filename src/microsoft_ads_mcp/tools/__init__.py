"""MCP tool registration, including the READ_ONLY gate for write tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ..config import Settings


def register_all(mcp: FastMCP, settings: Settings) -> None:
    """Register every tool. Write tools are registered only when not read-only.

    The READ_ONLY gate is enforced here by *conditional registration*: when
    ``settings.read_only`` is true, the write tools are never added to the server, so they
    cannot appear in ``list_tools`` or be invoked by any client.
    """
    from . import auth_tools, health, read_tools, reporting_tools

    health.register(mcp, settings)
    auth_tools.register(mcp, settings)
    read_tools.register(mcp)
    reporting_tools.register(mcp)

    if not settings.read_only:
        from . import write_tools

        write_tools.register(mcp)
