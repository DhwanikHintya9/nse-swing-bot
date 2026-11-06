import json
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nse_swing_bot.events.capture import capture_source_bytes
from nse_swing_bot.events.zip_inventory import inspect_captured_zip_package


def _capture_zip(tmp_path: Path, entries: list[tuple[str, bytes]], *, name="filing.zip"):
    source = tmp_path / name
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for member_name, data in entries:
            package.writestr(member_name, data)
    captured = capture_source_bytes(
        source,
        tmp_path / "archive",
        event_id="EV-ZIP-01",
        source_record_id="stage3c-zip-source",
        source_url="https://nsearchives.nseindia.com/corporate/filing.zip",
        document_type="exchange_filing_zip",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    return captured


def test_zip_inventory_hashes_members_and_binds_parent_capture(tmp_path):
    captured = _capture_zip(
        tmp_path,
        [("main.pdf", b"main filing"), ("Annexure A/annexure-a.pdf", b"annexure bytes")],
    )
    output = tmp_path / "inventory.json"

    result = inspect_captured_zip_package(captured.manifest_path, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result.member_count == 2
    assert result.archive_sha256 == captured.sha256
    assert payload["archive_sha256"] == captured.sha256
    assert payload["inventory_mode"] == "captured_zip_read_only_no_extraction"
    assert {member.name for member in result.members} == {
        "main.pdf",
        "Annexure A/annexure-a.pdf",
    }
    assert all(len(member.sha256) == 64 for member in result.members)
    assert not (tmp_path / "Annexure A").exists()


@pytest.mark.parametrize(
    "member_name",
    ["../escape.pdf", "/absolute.pdf", r"..\\escape.pdf", "C:/drive.pdf", "folder//file.pdf"],
)
def test_zip_inventory_rejects_unsafe_member_paths(tmp_path, member_name):
    captured = _capture_zip(tmp_path, [(member_name, b"payload")])
    with pytest.raises(ValueError, match="unsafe ZIP member path"):
        inspect_captured_zip_package(captured.manifest_path, tmp_path / "inventory.json")


def test_zip_inventory_rejects_duplicate_member_names(tmp_path):
    source = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(source, "w") as package:
            package.writestr("same.pdf", b"first")
            package.writestr("same.pdf", b"second")
    captured = capture_source_bytes(
        source,
        tmp_path / "archive",
        event_id="EV-ZIP-01",
        source_record_id="stage3c-zip-source",
        source_url="https://nsearchives.nseindia.com/corporate/filing.zip",
        document_type="exchange_filing_zip",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="duplicate ZIP member"):
        inspect_captured_zip_package(captured.manifest_path, tmp_path / "inventory.json")


def test_zip_inventory_rejects_symlink_members(tmp_path):
    source = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("linked.pdf")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(info, b"target.pdf")
    captured = capture_source_bytes(
        source,
        tmp_path / "archive",
        event_id="EV-ZIP-01",
        source_record_id="stage3c-zip-source",
        source_url="https://nsearchives.nseindia.com/corporate/filing.zip",
        document_type="exchange_filing_zip",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="symlink ZIP member"):
        inspect_captured_zip_package(captured.manifest_path, tmp_path / "inventory.json")


def test_zip_inventory_enforces_member_count_and_size_limits(tmp_path):
    captured = _capture_zip(tmp_path, [("one.pdf", b"12345"), ("two.pdf", b"67890")])
    with pytest.raises(ValueError, match="member count"):
        inspect_captured_zip_package(
            captured.manifest_path, tmp_path / "count.json", max_members=1
        )
    with pytest.raises(ValueError, match="member exceeds"):
        inspect_captured_zip_package(
            captured.manifest_path, tmp_path / "size.json", max_member_bytes=4
        )
    with pytest.raises(ValueError, match="total uncompressed"):
        inspect_captured_zip_package(
            captured.manifest_path, tmp_path / "total.json", max_total_uncompressed_bytes=8
        )


def test_zip_inventory_refuses_to_overwrite_inventory_manifest(tmp_path):
    captured = _capture_zip(tmp_path, [("main.pdf", b"filing")])
    output = tmp_path / "inventory.json"
    inspect_captured_zip_package(captured.manifest_path, output)
    before = output.read_bytes()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        inspect_captured_zip_package(captured.manifest_path, output)

    assert output.read_bytes() == before


def test_zip_inventory_rejects_non_zip_and_wrong_extension(tmp_path):
    source = tmp_path / "not-a-zip.zip"
    source.write_bytes(b"not a ZIP")
    captured = capture_source_bytes(
        source,
        tmp_path / "archive",
        event_id="EV-ZIP-01",
        source_record_id="stage3c-zip-source",
        source_url="https://nsearchives.nseindia.com/corporate/filing.zip",
        document_type="exchange_filing_zip",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="not a readable ZIP"):
        inspect_captured_zip_package(captured.manifest_path, tmp_path / "bad.json")

    pdf_source = tmp_path / "filing.pdf"
    pdf_source.write_bytes(b"%PDF-1.7")
    pdf_capture = capture_source_bytes(
        pdf_source,
        tmp_path / "archive-pdf",
        event_id="EV-PDF-01",
        source_record_id="stage3c-pdf-source",
        source_url="https://nsearchives.nseindia.com/corporate/filing.pdf",
        document_type="exchange_filing_pdf",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="must have a .zip extension"):
        inspect_captured_zip_package(pdf_capture.manifest_path, tmp_path / "pdf.json")


def test_zip_inventory_rejects_nonpositive_limits(tmp_path):
    captured = _capture_zip(tmp_path, [("main.pdf", b"filing")])
    with pytest.raises(ValueError, match="max_members"):
        inspect_captured_zip_package(
            captured.manifest_path, tmp_path / "inventory.json", max_members=0
        )



def test_zip_inventory_enforces_compression_ratio_limit(tmp_path):
    captured = _capture_zip(tmp_path, [("compressed.txt", b"A" * 20_000)])
    with pytest.raises(ValueError, match="compression ratio"):
        inspect_captured_zip_package(
            captured.manifest_path,
            tmp_path / "inventory.json",
            max_compression_ratio=2,
        )
