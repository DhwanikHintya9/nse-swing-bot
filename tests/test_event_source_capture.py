import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nse_swing_bot.events.capture import capture_source_bytes

CAPTURED = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _capture(source: Path, archive: Path, **overrides):
    arguments = {
        "event_id": "EV-THANGAMAYL-01",
        "source_record_id": "49a714705c25dd3fff9d",
        "source_url": "https://nsearchives.nseindia.com/corporate/filing.pdf",
        "document_type": "exchange_filing_pdf",
        "captured_at": CAPTURED,
    }
    arguments.update(overrides)
    return capture_source_bytes(source, archive, **arguments)


def test_capture_archives_exact_bytes_and_writes_sha256_manifest(tmp_path):
    source = tmp_path / "original.pdf"
    source_bytes = b"%PDF-1.7\nissuer original bytes\n"
    source.write_bytes(source_bytes)
    original_stat = source.stat()

    captured = _capture(source, tmp_path / "archive")

    assert captured.archive_path.read_bytes() == source_bytes
    assert captured.byte_length == len(source_bytes)
    assert captured.sha256 == hashlib.sha256(source_bytes).hexdigest()
    manifest = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == captured.sha256
    assert manifest["event_id"] == "EV-THANGAMAYL-01"
    assert manifest["source_record_id"] == "49a714705c25dd3fff9d"
    assert manifest["capture_mode"] == "local_original_bytes_no_network"
    assert source.read_bytes() == source_bytes
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns


def test_capture_refuses_to_overwrite_existing_archive(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"original")
    archive = tmp_path / "archive"

    first = _capture(source, archive)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _capture(source, archive)

    assert first.archive_path.read_bytes() == b"original"
    assert first.manifest_path.exists()


def test_capture_rejects_invalid_source_url(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"original")
    with pytest.raises(ValueError, match="absolute HTTP"):
        _capture(source, tmp_path / "archive", source_url="nseindia.com/filing.pdf")


def test_capture_rejects_unsafe_event_identifier(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"original")
    with pytest.raises(ValueError, match="event_id"):
        _capture(source, tmp_path / "archive", event_id="../escape")


def test_capture_requires_timezone_aware_capture_time(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"original")
    with pytest.raises(ValueError, match="timezone-aware"):
        _capture(source, tmp_path / "archive", captured_at=datetime(2026, 11, 6, 12, 0))
