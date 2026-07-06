"""FastMCP server entry point for psx-mcp-server."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import __version__

mcp = FastMCP("psx")


@mcp.tool()
def ping() -> str:
    """Health check. Returns the server version to confirm the MCP connection works."""
    return f"psx-mcp-server {__version__} ok"


def main() -> None:
    """Console-script entry point. Runs the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
