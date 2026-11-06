from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from nse_swing_bot.events.capture import capture_source_bytes
from nse_swing_bot.events.capture_verification import verify_capture_manifest


def _captured(tmp_path: Path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\\nverified bytes\\n")
    captured = capture_source_bytes(
        source,
        tmp_path / "archive",
        event_id="EV-TEST-01",
        source_record_id="source-001",
        source_url="https://nsearchives.nseindia.com/filing.pdf",
        document_type="exchange_filing_pdf",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    return captured


def test_verify_capture_manifest_confirms_hash_and_length(tmp_path):
    captured = _captured(tmp_path)
    verified = verify_capture_manifest(captured.manifest_path)

    assert verified.archive_path == captured.archive_path
    assert verified.event_id == "EV-TEST-01"
    assert verified.source_record_id == "source-001"
    assert verified.byte_length == captured.byte_length
    assert verified.sha256 == captured.sha256


def test_verify_capture_manifest_rejects_modified_bytes(tmp_path):
    captured = _captured(tmp_path)
    captured.archive_path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="byte_length mismatch|sha256 mismatch"):
        verify_capture_manifest(captured.manifest_path)


def test_verify_capture_manifest_rejects_manifest_length_tampering(tmp_path):
    captured = _captured(tmp_path)
    payload = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    payload["byte_length"] += 1
    captured.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="byte_length mismatch"):
        verify_capture_manifest(captured.manifest_path)


def test_verify_capture_manifest_rejects_path_traversal(tmp_path):
    captured = _captured(tmp_path)
    payload = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    payload["archive_filename"] = "../outside.pdf"
    captured.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="basename"):
        verify_capture_manifest(captured.manifest_path)


def test_verify_capture_manifest_rejects_naive_timestamp(tmp_path):
    captured = _captured(tmp_path)
    payload = json.loads(captured.manifest_path.read_text(encoding="utf-8"))
    payload["captured_at"] = "2026-11-06T12:00:00"
    captured.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="timezone offset"):
        verify_capture_manifest(captured.manifest_path)
