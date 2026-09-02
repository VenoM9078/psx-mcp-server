"""Tests for the richer global announcements parser."""

from __future__ import annotations

from psx_mcp_server.parsers.announcements import parse_global_announcements, sort_announcements


def test_global_announcements_sort_by_date_and_time_before_limit(fixture):
    announcements, total = parse_global_announcements(
        fixture("announcements_HBL.html"),
        source="https://dps.psx.com.pk/announcements",
        raw_type="C",
    )

    assert total == 4
    ordered = sort_announcements(announcements)
    assert [(a.date, a.time) for a in ordered] == [
        ("2026-06-17", "8:00 AM"),
        ("2026-04-28", "2:00 PM"),
        ("2026-04-28", "9:00 AM"),
        ("2026-04-01", "9:00 AM"),
    ]
    assert ordered[0].raw_type == "C"
    assert ordered[0].pdf_url is None
    assert ordered[0].image_url == "https://dps.psx.com.pk/download/image/3.gif"
    assert ordered[1].pdf_url == "/download/document/275409.pdf"


def test_global_announcements_malformed_response_is_empty():
    announcements, total = parse_global_announcements("<html></html>")
    assert announcements == []
    assert total is None


def test_query_string_pdf_is_detected_but_arbitrary_substrings_are_not():
    html = """
    <div id="announcementsTable"><table><tbody>
      <tr><td>2026-01-02</td><td>09:00</td><td>UBL</td><td></td><td>Valid</td>
        <td><a href="/download/document/file.pdf?id=1">PDF</a></td></tr>
      <tr><td>2026-01-01</td><td>09:00</td><td>UBL</td><td></td><td>Not a document</td>
        <td><a href="/page?next=/download/document/file.pdf">Page</a></td></tr>
    </tbody></table></div>
    """

    announcements, _ = parse_global_announcements(html)

    assert announcements[0].pdf_url == "/download/document/file.pdf?id=1"
    assert announcements[1].pdf_url is None
