"""FastMCP server entry point for psx-mcp-server.

Wires one shared PSXClient into the tool/resource layers and runs over stdio.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from .client import PSXClient
from .prompts import register_prompts
from .resources import register_resources
from .tools import register_tools

# One client for the whole process. Constructing httpx.AsyncClient here is safe
# (no running loop needed); the lifespan below closes it on shutdown.
_client = PSXClient()


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[dict]:
    try:
        yield {}
    finally:
        await _client.close()


mcp = FastMCP(
    "psx",
    instructions=(
        "Live Pakistan Stock Exchange (PSX) data: quotes, intraday and end-of-day "
        "history, indices (KSE-100 and others), company fundamentals, dividends and "
        "announcements. Prices are in PKR; times are Pakistan Standard Time (UTC+5). "
        "If unsure of a ticker, call search_symbols first. Data is from the public "
        "PSX Data Portal and is informational only, not investment advice."
    ),
    lifespan=_lifespan,
)

register_tools(mcp, _client)
register_resources(mcp, _client)
register_prompts(mcp)


def main() -> None:
    """Console-script entry point. Runs the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
