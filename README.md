# psx-mcp-server

[![CI](https://github.com/ahmedraza-96/psx-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/ahmedraza-96/psx-mcp-server/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/psx-mcp-server.svg)](https://pypi.org/project/psx-mcp-server/)
[![Python](https://img.shields.io/pypi/pyversions/psx-mcp-server.svg)](https://pypi.org/project/psx-mcp-server/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives Claude and other
MCP agents live **Pakistan Stock Exchange** data — quotes, intraday and end-of-day history,
indices (KSE-100 and 17 others), company summaries, reports, compliance evidence, dividends,
announcements, and close-only performance analytics — sourced from the public
[PSX Data Portal](https://dps.psx.com.pk). No API key required.

## Quick start

The server runs via [`uv`](https://docs.astral.sh/uv/) — `uvx` fetches and runs it in one step,
so there is nothing to install manually.

**Claude Code:**

```bash
claude mcp add psx -- uvx psx-mcp-server
```

**Claude Desktop** — add to `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "psx": {
      "command": "uvx",
      "args": ["psx-mcp-server"]
    }
  }
}
```

**Any MCP client:** run `uvx psx-mcp-server` (stdio transport). Requires `uv`
([install guide](https://docs.astral.sh/uv/getting-started/installation/)).

### Remote HTTP transport

For a remote MCP client, run the same server over unauthenticated Streamable HTTP:

```bash
psx-mcp-http --host 127.0.0.1 --port 8000 \
  --allowed-host psx.thisisroushan.com \
  --allowed-host 'psx.thisisroushan.com:*'
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Keep this backend on loopback and
terminate TLS and apply rate limiting at the reverse proxy, exposing it externally as
`https://psx.thisisroushan.com/mcp`. This entry point intentionally has no authentication:
the server exposes public, read-only PSX data and does not accept trading or portfolio
mutations. Do not expose the backend port directly to the Internet.

## Example

> **You:** Which PSX stocks gained the most today, and what's HBL trading at?

The agent calls `get_market_snapshot` and `get_quote`, and answers:

```
TOP 5 GAINERS:
  TCORPR2  +22.62%  Rs.5.42
  PINL     +10.52%  Rs.10.51
  HICL     +10.05%  Rs.11.50
  TSPL     +10.02%  Rs.18.12
  CLVL     +10.02%  Rs.22.41
  breadth: 296 advancers / 180 decliners

HBL: Habib Bank Limited | current Rs.318.15 | P/E 7.43
KSE100: 187,454.69 (+1.12%)
```

## Tools

| Tool | Parameters | Returns |
|------|------------|---------|
| `search_symbols` | `query`, `sector?`, `limit=20` | Matching tickers (exact matches first). Use first if unsure of a ticker. |
| `get_quote` | `symbol` | Current price, LDCP, OHL, signed change %, volume, bid/ask, 52-week range, P/E (PKR). Includes source/freshness metadata and P/E-basis warning. |
| `get_intraday` | `symbol`, `interval="5min"`, `limit=50` | Intraday OHLCV bars (or `raw` ticks) for the latest session, PKT times. |
| `get_eod_history` | `symbol`, `start_date?`, `end_date?`, `limit=260` | Daily open/close/volume (~5 yrs). Works for indices. No high/low. |
| `get_ohlc_history` | `symbol`, `month`, `year` | Full daily OHLCV for one month — the only free source of daily high/low. |
| `get_market_snapshot` | `category="gainers"`, `limit=15`, `sector?` | Top movers (`gainers`/`losers`/`volume`) plus market-wide and, when filtered, sector-scoped breadth. |
| `get_indices` | — | All ~18 PSX indices with change %. |
| `get_company_info` | `symbol` | Business description, sector, market cap, shares, free float, P/E, and source/basis metadata. |
| `get_dividends` | `symbol`, `limit=10` | Payout history with verbatim PSX notation, conservative cash/bonus/right classification, and book-closure dates. |
| `get_announcements` | `symbol`, `limit=10`, `date_from?`, `date_to?`, `query?` | Globally date/time-sorted company announcements with raw type, PDF, image, and source metadata. |
| `get_financials` | `symbol`, `view="all"`, `annual_limit=5`, `quarterly_limit=8` | Structured annual/quarterly company-page summary facts and ratios, with raw labels, units, scale, basis, and ambiguity warnings. |
| `get_company_reports` | `symbol`, `fiscal_year?`, `limit=20` | Official report catalogue metadata (type, period ended, posting date, URL); does not download or parse PDFs. |
| `get_company_alerts` | `symbol` | Current listing/status evidence for non-compliance, RWA, suspension, and winding-up using true/false/unknown states. |
| `get_price_performance` | `symbol`, `windows?`, `benchmark_symbol="KSE100"`, `include_volume=true`, `include_volatility=true`, `include_drawdown=true` | Deterministic close-only returns, aligned benchmark returns, relative performance, volume, volatility, drawdown, and methodology. |

**Resources:** `psx://symbols` (full ticker directory), `psx://sectors` (sector names),
`psx://indices` (current index values).

**Prompts:** `analyze_stock(symbol)` (single-stock research brief),
`market_overview()` (today's market wrap).

## Notes

- **Prices are in PKR**; timestamps are Pakistan Standard Time (UTC+5, no DST).
- PSX trades **Monday–Friday, ~09:30–15:30 PKT**. Outside those hours, quotes reflect the last
  session and intraday data may be empty.
- The quote P/E is returned with `pe_basis="unconsolidated"` when PSX supplies it; it is not a
  consolidated P/E. Company-page financial summaries use `basis="unknown"` unless the source
  establishes a basis.
- Company financial tables state **all numbers are in thousands (000's) except EPS**. Responses
  preserve the displayed value, unit scale, and a separately labeled normalized value; EPS is
  never multiplied by 1,000. Only confident amount metrics are scaled; unknown rows return
  `unit="unknown"`, `unit_scale=null`, and `normalized_value=null`. Annual values are marked
  `full_year`, while Q1/Q2/Q3 values remain `unknown` for standalone-versus-cumulative semantics.
- Dividend strings such as `60%(i) (D)` remain verbatim. Percentages are not converted to PKR/share
  because the event face value is not assumed; `cash_dividend_per_share` is null with a warning
  when that input is unavailable.
- `get_price_performance` uses EOD closes only: returns are close-to-close, volatility is annualized
  sample standard deviation using `sqrt(252)`, and drawdown is the **maximum close-to-close
  drawdown** (losses are negative). `1M/3M/6M` use calendar months, `1Y/3Y/5Y` use calendar
  years, `1W` uses a seven-calendar-day target, and YTD starts at the last available close on or
  before the prior year-end. Relative benchmark returns require exactly matching effective dates;
  incomplete windows expose `complete=false`/`coverage="partial"`. Results are not dividend-adjusted,
  and explicit split-adjustment semantics are not confirmed by the source.
- Compliance outputs are evidence-based and tri-state. A generic hidden `.footer__rwaModal` is not
  treated as an active Risk Warning Alert; absence of current evidence does not prove historical
  absence.
- Responses are cached briefly (30 s intraday, 5 min for shared company pages, 5–15 min for
  announcements/listings, 1 h for EOD history, 24 h for reports, and 24 h for the symbol
  directory) to be polite to the portal. Responses expose `source_fetched_at`, `served_at`,
  `cache_age_seconds`, and `from_cache`, so a cache hit is not presented as a new upstream fetch.
  Announcement pagination and all tool limits are bounded; per-client rate limiting for a public
  deployment belongs at the reverse proxy. Override the request identity with the
  `PSX_MCP_USER_AGENT` environment variable.

## Development

```bash
git clone https://github.com/ahmedraza-96/psx-mcp-server
cd psx-mcp-server
uv sync

uv run pytest                 # unit tests (mocked, offline)
uv run ruff check . && uv run ruff format --check .

# Live tests hit the real portal — run during PKT market hours:
uv run pytest -m live --override-ini "addopts="

# Re-record test fixtures if PSX changes its markup:
uv run python scripts/record_fixtures.py
```

Architecture: `parsers/` are pure functions (raw response in, dataclasses out) tested against
committed fixtures in `tests/fixtures/`; `client.py` owns all HTTP I/O (caching, retries, error
mapping); `tools.py` composes the two into MCP tools. See
[CHANGELOG.md](CHANGELOG.md) for release history.

## Disclaimer

This is an unofficial project and is **not affiliated with or endorsed by the Pakistan Stock
Exchange**. Data comes from the public PSX Data Portal (dps.psx.com.pk) and may be delayed or
inaccurate. For licensed or commercial market data, contact `marketdatarequest@psx.com.pk`.
**Nothing here is investment advice.**

## License

[MIT](LICENSE) © Ahmed Raza
