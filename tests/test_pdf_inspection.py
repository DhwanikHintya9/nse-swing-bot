import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pypdf import PdfWriter

from nse_swing_bot.events.capture import capture_source_bytes
from nse_swing_bot.events.pdf_inspection import (
    inspect_captured_pdf,
    verify_exact_pdf_excerpt,
    write_excerpt_verification,
)


def _capture_pdf(tmp_path: Path):
    source = tmp_path / "filing.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({
        "/Title": "Issuer Board Outcome",
        "/Author": "Issuer Limited",
        "/Subject": "Board meeting outcome",
    })
    writer.add_outline_item("Annexure A — Appointment", 0)
    writer.add_attachment("annexure-a.txt", b"attachment evidence")
    with source.open("wb") as stream:
        writer.write(stream)
    return capture_source_bytes(
        source, tmp_path / "capture",
        event_id="EV-PDF-01", source_record_id="source-pdf-01",
        source_url="https://nsearchives.nseindia.com/corporate/filing.pdf",
        document_type="issuer_filing_pdf",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )


def test_pdf_inspection_records_metadata_pages_bookmarks_and_attachments(tmp_path):
    capture = _capture_pdf(tmp_path)
    output = inspect_captured_pdf(capture.manifest_path, tmp_path / "inspection.json")
    payload = json.loads(output.read_text())
    assert payload["event_id"] == "EV-PDF-01"
    assert payload["page_count"] == 1
    assert payload["metadata"]["title"] == "Issuer Board Outcome"
    assert payload["metadata"]["author"] == "Issuer Limited"
    assert payload["bookmarks"] == [
        {"title": "Annexure A — Appointment", "page_number": 1}
    ]
    assert payload["embedded_attachment_count"] == 1
    assert payload["embedded_attachment_names"] == ["annexure-a.txt"]
    assert payload["pages"][0]["has_extractable_text"] is False
    assert "not proof of annexure completeness" in " ".join(
        payload["inspection_limitations"]
    )


def test_pdf_inspection_refuses_overwrite_and_non_pdf(tmp_path):
    capture = _capture_pdf(tmp_path)
    output = tmp_path / "inspection.json"
    inspect_captured_pdf(capture.manifest_path, output)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        inspect_captured_pdf(capture.manifest_path, output)
    with pytest.raises(ValueError, match="positive integer"):
        inspect_captured_pdf(capture.manifest_path, tmp_path / "other.json", max_pages=0)
    with pytest.raises(ValueError, match="positive integer"):
        inspect_captured_pdf(
            capture.manifest_path, tmp_path / "third.json", max_embedded_files=0
        )


def test_pdf_excerpt_requires_exact_page_text_and_is_not_normalized(
    tmp_path, monkeypatch
):
    capture = _capture_pdf(tmp_path)

    class FakePage:
        def extract_text(self):
            return "Director appointed for five years."

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(
        "nse_swing_bot.events.pdf_inspection.PdfReader", FakeReader
    )
    result = verify_exact_pdf_excerpt(
        capture.manifest_path, 1, "appointed for five years"
    )
    assert result["verification_mode"] == "exact_substring_match_no_normalization"
    assert result["evidence_review_status"] == "pending"
    with pytest.raises(ValueError, match="does not occur"):
        verify_exact_pdf_excerpt(
            capture.manifest_path, 1, "appointed  for five years"
        )
    with pytest.raises(ValueError, match="exceeds PDF page count"):
        verify_exact_pdf_excerpt(capture.manifest_path, 2, "appointed")


def test_excerpt_verification_manifest_is_immutable(tmp_path, monkeypatch):
    capture = _capture_pdf(tmp_path)

    class FakePage:
        def extract_text(self):
            return "Appointment effective 6 November 2026."

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(
        "nse_swing_bot.events.pdf_inspection.PdfReader", FakeReader
    )
    output = tmp_path / "excerpt.json"
    write_excerpt_verification(
        capture.manifest_path, output, 1, "effective 6 November 2026"
    )
    payload = json.loads(output.read_text())
    assert payload["page_number"] == 1
    assert payload["exact_excerpt"] == "effective 6 November 2026"
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_excerpt_verification(
            capture.manifest_path, output, 1, "effective 6 November 2026"
        )
