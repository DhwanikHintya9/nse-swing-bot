import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nse_swing_bot.events.capture import capture_source_bytes
from nse_swing_bot.events.capture_verification import verify_capture_manifest
from nse_swing_bot.events.zip_inventory import inspect_captured_zip_package
from nse_swing_bot.events.zip_member_capture import materialize_verified_zip_member


def _package(tmp_path: Path):
    source = tmp_path / "filing.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("docs/Annexure A.pdf", b"%PDF-1.7\\nannexure evidence")
        package.writestr("main.pdf", b"%PDF-1.7\\nmain filing")
    captured = capture_source_bytes(
        source, tmp_path / "parent",
        event_id="EV-ZIP-10", source_record_id="source-10",
        source_url="https://nsearchives.nseindia.com/corporate/filing.zip",
        document_type="exchange_filing_zip",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    inventory_path = tmp_path / "inventory.json"
    inspect_captured_zip_package(captured.manifest_path, inventory_path)
    return captured, inventory_path


def _materialize(tmp_path, captured, inventory):
    return materialize_verified_zip_member(
        captured.manifest_path, inventory, "docs/Annexure A.pdf", tmp_path / "children",
        captured_at=datetime(2026, 11, 6, 13, 0, tzinfo=UTC),
    )


def test_materialized_member_has_verified_parent_lineage(tmp_path):
    parent, inventory = _package(tmp_path)
    child_manifest = _materialize(tmp_path, parent, inventory)
    child = verify_capture_manifest(child_manifest)
    payload = json.loads(child_manifest.read_text())
    assert child.event_id == parent.event_id
    assert child.source_record_id == parent.source_record_id
    assert child.document_type == "archive_member_pdf"
    assert child.archive_path.read_bytes() == b"%PDF-1.7\\nannexure evidence"
    assert payload["parent_archive_sha256"] == parent.sha256
    assert payload["member_name"] == "docs/Annexure A.pdf"
    assert payload["capture_mode"] == "zip_member_original_bytes_no_network"


def test_materialization_rejects_inventory_digest_tampering(tmp_path):
    parent, inventory = _package(tmp_path)
    payload = json.loads(inventory.read_text())
    payload["members"][0]["sha256"] = "0" * 64
    inventory.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="do not match inventory"):
        _materialize(tmp_path, parent, inventory)


def test_materialization_rejects_parent_inventory_mismatch(tmp_path):
    parent, inventory = _package(tmp_path)
    payload = json.loads(inventory.read_text())
    payload["archive_sha256"] = "0" * 64
    inventory.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="archive_sha256"):
        _materialize(tmp_path, parent, inventory)


def test_materialization_rejects_unknown_or_ambiguous_member(tmp_path):
    parent, inventory = _package(tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        materialize_verified_zip_member(
            parent.manifest_path, inventory, "../escape.pdf", tmp_path / "out",
            captured_at=datetime(2026, 11, 6, 13, 0, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="exactly one"):
        materialize_verified_zip_member(
            parent.manifest_path, inventory, "missing.pdf", tmp_path / "out",
            captured_at=datetime(2026, 11, 6, 13, 0, tzinfo=UTC),
        )


def test_materialization_refuses_overwrite(tmp_path):
    parent, inventory = _package(tmp_path)
    first = _materialize(tmp_path, parent, inventory)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _materialize(tmp_path, parent, inventory)
    assert first.exists()


def test_child_verifier_rejects_parent_digest_tampering(tmp_path):
    parent, inventory = _package(tmp_path)
    child_manifest = _materialize(tmp_path, parent, inventory)
    payload = json.loads(child_manifest.read_text())
    payload["parent_archive_sha256"] = "0" * 64
    child_manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="parent archive SHA-256"):
        verify_capture_manifest(child_manifest)
