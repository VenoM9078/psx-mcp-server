"""Record live PSX Data Portal responses into tests/fixtures/.

Run once to (re-)capture the golden fixtures the parser tests assert against:

    uv run python scripts/record_fixtures.py

Be polite: this sleeps 1s between requests. Re-run only when PSX changes its
markup and a parser test starts failing against a stale fixture. Committed
fixtures are what CI runs against, so they must stay in the repo.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

BASE = "https://dps.psx.com.pk"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
USER_AGENT = "psx-mcp-server-fixture-recorder/0.1 (+https://github.com/ahemdraza-96/psx-mcp-server)"
DELAY_SECONDS = 1.0

# (filename, method, path, form-data-or-None)
TARGETS: list[tuple[str, str, str, dict[str, str] | None]] = [
    ("symbols.json", "GET", "/symbols", None),
    ("timeseries_int_HBL.json", "GET", "/timeseries/int/HBL", None),
    ("timeseries_eod_HBL.json", "GET", "/timeseries/eod/HBL", None),
    ("timeseries_eod_KSE100.json", "GET", "/timeseries/eod/KSE100", None),
    ("company_HBL.html", "GET", "/company/HBL", None),
    # Payouts/dividends load via a separate AJAX POST (empty in the company page HTML).
    ("payouts_HBL.html", "POST", "/company/payouts", {"symbol": "HBL"}),
    # A bogus symbol — pins how the portal responds to unknown tickers so the
    # not-found detection logic can be tested against reality.
    ("company_UNKNOWN.html", "GET", "/company/ZZZZINVALID", None),
    ("market_watch.html", "GET", "/market-watch", None),
    ("indices.html", "GET", "/indices", None),
    # A past month that definitely has data.
    (
        "historical_HBL_2026_06.html",
        "POST",
        "/historical",
        {"month": "6", "year": "2026", "symbol": "HBL"},
    ),
    # A far-future month — should come back empty; pins the empty-table shape.
    (
        "historical_empty.html",
        "POST",
        "/historical",
        {"month": "1", "year": "2050", "symbol": "HBL"},
    ),
]


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}
    with httpx.Client(
        base_url=BASE, headers=headers, timeout=30.0, follow_redirects=True
    ) as client:
        for i, (name, method, path, data) in enumerate(TARGETS):
            if i:
                time.sleep(DELAY_SECONDS)
            extra = {"X-Requested-With": "XMLHttpRequest"} if method == "POST" else {}
            resp = client.request(method, path, data=data, headers=extra)
            out = FIXTURES / name
            out.write_text(resp.text, encoding="utf-8")
            print(
                f"{method:4} {path:40} -> {name:32} [{resp.status_code}] {len(resp.text):>8} bytes"
            )


if __name__ == "__main__":
    main()
