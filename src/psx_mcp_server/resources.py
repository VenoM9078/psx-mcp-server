"""MCP resources — read-only data an agent can bulk-load without a tool call."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .client import PSXClient
from .parsers.indices import parse_indices
from .parsers.symbols import parse_symbols


def register_resources(mcp: FastMCP, client: PSXClient) -> None:
    @mcp.resource("psx://symbols", mime_type="application/json")
    async def symbols_directory() -> str:
        """The full PSX symbol directory (ticker, name, sector, ETF/debt flags)."""
        symbols = parse_symbols(await client.fetch_symbols())
        return json.dumps([s.to_dict() for s in symbols])

    @mcp.resource("psx://sectors", mime_type="application/json")
    async def sector_list() -> str:
        """Distinct PSX sector names — valid values for the `sector` tool params."""
        symbols = parse_symbols(await client.fetch_symbols())
        return json.dumps(sorted({s.sector for s in symbols if s.sector}))

    @mcp.resource("psx://indices", mime_type="application/json")
    async def indices_snapshot() -> str:
        """Current values for all PSX indices."""
        indices = parse_indices(await client.fetch_indices())
        return json.dumps([i.to_dict() for i in indices])
