"""Manual end-to-end check: drive the server as a real MCP client against LIVE
PSX data. Not part of the test suite. Run: uv run python scripts/live_e2e.py
"""

import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command="psx-mcp-server", args=[])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        snap = await session.call_tool("get_market_snapshot", {"category": "gainers", "limit": 5})
        d = json.loads(snap.content[0].text)
        print("TOP 5 GAINERS:")
        for r in d["rows"]:
            print(f"  {r['symbol']:8} {r['change_pct']:+6.2f}%  Rs.{r['current']}")
        s = d["market_summary"]
        print(f"  breadth: {s['advancers']} advancers / {s['decliners']} decliners")

        q = json.loads((await session.call_tool("get_quote", {"symbol": "HBL"})).content[0].text)
        print(f"\nHBL: {q['name']} | current Rs.{q['current']} | P/E {q['pe_ratio']}")

        idx = json.loads((await session.call_tool("get_indices", {})).content[0].text)
        kse = next(i for i in idx["indices"] if i["name"] == "KSE100")
        print(f"KSE100: {kse['current']} ({kse['change_pct']:+.2f}%)")


if __name__ == "__main__":
    asyncio.run(main())
