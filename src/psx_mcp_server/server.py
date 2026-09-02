"""FastMCP server entry points for psx-mcp-server.

Wires one shared PSXClient into the tool/resource layers. The default console
entry point runs over stdio; the separate ``psx-mcp-http`` entry point runs the
same read-only server over unauthenticated Streamable HTTP.
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

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
        "history, indices (KSE-100 and others), company summaries/reports, compliance "
        "evidence, dividends, announcements, and close-only performance analytics. "
        "Prices are in PKR; times are Pakistan Standard Time (UTC+5). "
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


def http_main() -> None:
    """Console-script entry point for unauthenticated Streamable HTTP.

    The backend binds to loopback by default so TLS, rate limiting, and public
    exposure remain the responsibility of the VPS reverse proxy. Authentication
    is intentionally not configured because this server only exposes public,
    read-only PSX data.
    """
    parser = argparse.ArgumentParser(description="Run the PSX MCP server over Streamable HTTP.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address for the local HTTP backend (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        default=8000,
        type=int,
        help="Local HTTP backend port (default: 8000).",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help=(
            "Additional Host header accepted by DNS-rebinding protection. "
            "Repeat for exact and wildcard-port values when needed."
        ),
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help=(
            "Additional Origin header accepted by DNS-rebinding protection. "
            "Repeat when a client sends an Origin header."
        ),
    )
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            *args.allowed_host,
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            *args.allowed_origin,
        ],
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
