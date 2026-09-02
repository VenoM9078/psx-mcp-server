"""Focused tests for shared numeric normalization."""

from __future__ import annotations

import pytest

from psx_mcp_server._util import parse_int, parse_number


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(56.08)", -56.08),
        ("-56.08", -56.08),
        ("56.08", 56.08),
        ("+56.08", 56.08),
        ("5,426,927", 5426927.0),
        ("0", 0.0),
        ("  12.50%  ", 12.5),
        ("Rs. 12.50", 12.5),
    ],
)
def test_parse_number_supported_psx_forms(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", [None, "", " ", "-", "--", "N/A", "n/a", "not a number"])
def test_parse_number_missing_or_unparseable_is_none(text):
    assert parse_number(text) is None


def test_parse_int_handles_parenthesized_integer():
    assert parse_int("(1,200)") == -1200
