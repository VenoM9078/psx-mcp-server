# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/ahemdraza-96/psx-mcp-server/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ahemdraza-96/psx-mcp-server/releases/tag/v0.1.0
