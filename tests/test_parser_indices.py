"""Tests for the /indices HTML parser."""

from __future__ import annotations

import pytest

from psx_mcp_server.errors import ParseError
from psx_mcp_server.parsers.indices import parse_indices


def test_parse_indices_count(fixture):
    indices = parse_indices(fixture("indices.html"))
    assert len(indices) == 18


def test_parse_indices_kse100(fixture):
    indices = parse_indices(fixture("indices.html"))
    kse = next(i for i in indices if i.name == "KSE100")
    assert kse.high == 187546.36
    assert kse.low == 185910.38
    assert kse.current == 187454.69
    assert kse.change == 2082.49
    assert kse.change_pct == 1.12


@pytest.mark.parametrize("bad", ["", "<html><body>nothing</body></html>"])
def test_parse_indices_no_table_raises(bad):
    with pytest.raises(ParseError):
        parse_indices(bad)
