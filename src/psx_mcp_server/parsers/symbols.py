"""Parse the /symbols JSON directory of listed securities."""

from __future__ import annotations

import json

from ..errors import ParseError
from ..models import Symbol


def parse_symbols(text: str) -> list[Symbol]:
    """JSON array of {symbol, name, sectorName, isETF, isDebt, isGEM?} -> list[Symbol]."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ParseError("the symbols directory") from exc
    if not isinstance(payload, list):
        raise ParseError("the symbols directory")
    symbols: list[Symbol] = []
    for rec in payload:
        symbols.append(
            Symbol(
                symbol=rec["symbol"],
                name=rec.get("name", ""),
                sector=rec.get("sectorName", ""),
                is_etf=bool(rec.get("isETF", False)),
                is_debt=bool(rec.get("isDebt", False)),
                is_gem=bool(rec.get("isGEM", False)),
            )
        )
    return symbols
