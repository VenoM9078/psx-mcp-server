"""MCP prompts — reusable multi-step workflows an agent can invoke."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

_DISCLAIMER = (
    "End with a one-line reminder that this is informational only, sourced from "
    "the public PSX Data Portal, and not investment advice."
)


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt()
    def analyze_stock(symbol: str) -> str:
        """Produce a research brief for a single PSX stock."""
        return (
            f"Produce a concise investment research brief for the PSX-listed stock "
            f"'{symbol}'. Use the PSX tools to gather data, then synthesize:\n"
            f"1. Call get_quote({symbol!r}) for the current price and day range.\n"
            f"2. Call get_company_info({symbol!r}) for the business, sector, market "
            f"cap and P/E.\n"
            f"3. Call get_eod_history({symbol!r}, limit=250) and summarize the ~1-year "
            f"price trend (high, low, rough % change).\n"
            f"4. Call get_dividends({symbol!r}) and get_announcements({symbol!r}) for "
            f"recent payouts and corporate actions.\n"
            f"5. Call get_eod_history('KSE100', limit=250) and compare the stock's "
            f"trend against the KSE-100 index.\n\n"
            f"Present valuation, momentum, income (dividends) and any notable news. "
            f"{_DISCLAIMER}"
        )

    @mcp.prompt()
    def market_overview() -> str:
        """Summarize the state of the PSX market today."""
        return (
            "Give an overview of the Pakistan Stock Exchange today. Use the tools:\n"
            "1. Call get_indices() and report KSE-100 with its change %, plus KSE-30 "
            "and KMI-30.\n"
            "2. Call get_market_snapshot(category='gainers') and "
            "get_market_snapshot(category='losers') for the top movers.\n"
            "3. Call get_market_snapshot(category='volume') for the most actively "
            "traded stocks.\n"
            "4. Use the market breadth summary (advancers vs decliners) to describe "
            "overall sentiment.\n\n"
            "Write a short, readable market wrap. " + _DISCLAIMER
        )
