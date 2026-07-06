"""Error taxonomy. Every error carries an agent-readable message.

Tools catch PSXError and surface `.message` to the calling agent verbatim
instead of a stack trace, so messages are written as guidance the model can act
on (e.g. "use search_symbols to find the correct ticker").
"""

from __future__ import annotations


class PSXError(Exception):
    """Base class for all psx-mcp-server errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SymbolNotFoundError(PSXError):
    """The requested ticker does not exist on PSX."""

    def __init__(self, symbol: str) -> None:
        super().__init__(
            f"Unknown PSX symbol '{symbol}'. Use the search_symbols tool to find the "
            f"correct ticker (e.g. 'Habib Bank' -> HBL)."
        )
        self.symbol = symbol


class NoDataError(PSXError):
    """The symbol is valid but the endpoint returned no data right now."""


class PSXUnavailableError(PSXError):
    """The PSX Data Portal did not respond successfully after retries."""


class ParseError(PSXError):
    """A PSX response could not be parsed — the site layout likely changed."""

    def __init__(self, what: str) -> None:
        super().__init__(
            f"Could not parse the PSX response for {what} — the website layout may have "
            f"changed. Please report this at "
            f"https://github.com/ahmedraza-96/psx-mcp-server/issues."
        )
