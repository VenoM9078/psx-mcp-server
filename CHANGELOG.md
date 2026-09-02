# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Separate `psx-mcp-http` entry point for unauthenticated Streamable HTTP access to the
  existing read-only server; the default stdio entry point is unchanged.
- Structured company financial summaries/ratios, official report discovery, evidence-based
  compliance alerts, and close-only price-performance analytics.

### Changed
- Preserve signed quote changes, add source/freshness metadata, make market breadth scope
  explicit, globally sort announcements before truncation, and classify payout notation without
  assuming a face value or converting percentages into DPS.
- Targeted correctness repair: financial grids now fail closed on ambiguous alignment, unknown
  financial rows are not scaled, Sales keeps the `sales` metric, and report/year/URL parsing is
  explicit and bounded.
- Targeted correctness repair: performance windows use calendar arithmetic, maximum close-to-close
  drawdown is now a negative loss percentage, benchmark-relative returns require exact effective
  date alignment, and stock analytics survive benchmark failure.
- Targeted correctness repair: DC/non-compliance evidence is separate from RWA, suspension and
  winding-up remain unknown without affirmative evidence, alert sources degrade independently,
  announcement attribution requires an exact returned symbol, and cache freshness distinguishes
  upstream fetch time from response service time.

## [0.1.0] - 2026-07-07

### Added
- Initial release: a Model Context Protocol server for Pakistan Stock Exchange data.
- 10 tools: `search_symbols`, `get_quote`, `get_intraday`, `get_eod_history`,
  `get_ohlc_history`, `get_market_snapshot`, `get_indices`, `get_company_info`,
  `get_dividends`, `get_announcements`.
- 3 resources: `psx://symbols`, `psx://sectors`, `psx://indices`.
- 2 prompts: `analyze_stock`, `market_overview`.
- In-memory TTL caching, retry/backoff, and agent-readable error messages.
- Test suite with committed fixtures plus opt-in live smoke tests.

[Unreleased]: https://github.com/ahmedraza-96/psx-mcp-server/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ahmedraza-96/psx-mcp-server/releases/tag/v0.1.0
