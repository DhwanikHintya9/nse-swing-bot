"""Integrity verification for locally captured source-byte manifests."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class VerifiedCapture:
    manifest_path: Path
    archive_path: Path
    event_id: str
    source_record_id: str
    source_url: str
    document_type: str
    byte_length: int
    sha256: str
    captured_at: datetime


def _required_text(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def verify_capture_manifest(manifest_path: Path) -> VerifiedCapture:
    """Verify manifest structure, path safety, byte length and SHA-256.

    Verification proves byte integrity only. It does not prove source authenticity,
    document completeness, direct review, or evidence acceptance.
    """
    manifest = manifest_path.expanduser().resolve(strict=True)
    if not manifest.is_file():
        raise ValueError("manifest_path must identify a regular file")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported capture manifest schema_version")
    capture_mode = payload.get("capture_mode")
    if capture_mode not in {
        "local_original_bytes_no_network",
        "zip_member_original_bytes_no_network",
    }:
        raise ValueError("unsupported capture_mode")

    event_id = _required_text(payload, "event_id")
    source_record_id = _required_text(payload, "source_record_id")
    for field, value in (("event_id", event_id), ("source_record_id", source_record_id)):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
            raise ValueError(f"unsafe {field}")
    source_url = _required_text(payload, "source_url")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        raise ValueError("source_url must be an absolute HTTP(S) URL")
    document_type = _required_text(payload, "document_type")
    archive_filename = _required_text(payload, "archive_filename")
    if (
        Path(archive_filename).name != archive_filename
        or archive_filename in {".", ".."}
        or "/" in archive_filename
        or "\\" in archive_filename
    ):
        raise ValueError("archive_filename must be a basename")
    if not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("sha256", ""))):
        raise ValueError("sha256 must be a lowercase 64-character hex digest")
    byte_length = payload.get("byte_length")
    if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
        raise ValueError("byte_length must be a positive integer")
    captured_at_raw = _required_text(payload, "captured_at")
    try:
        captured_at = datetime.fromisoformat(captured_at_raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("captured_at must be an ISO-8601 timestamp") from error
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must include a timezone offset")

    archive_path = manifest.parent / archive_filename
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("archived source must be a regular, non-symlink file")
    if archive_path.resolve(strict=True).parent != manifest.parent:
        raise ValueError("archived source must remain beside its manifest")
    digest = hashlib.sha256()
    actual_length = 0
    with archive_path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            actual_length += len(chunk)
    if actual_length != byte_length:
        raise ValueError(
            f"byte_length mismatch: manifest={byte_length}, actual={actual_length}"
        )
    expected_sha256 = str(payload["sha256"])
    if digest.hexdigest() != expected_sha256:
        raise ValueError("sha256 mismatch: archived source bytes do not match manifest")

    if capture_mode == "zip_member_original_bytes_no_network":
        parent_raw = _required_text(payload, "parent_capture_manifest_path")
        parent_path = Path(parent_raw).expanduser().resolve(strict=True)
        parent = verify_capture_manifest(parent_path)
        if parent.archive_path.suffix.lower() != ".zip":
            raise ValueError("ZIP-member parent must be a ZIP archive")
        parent_identity = (parent.event_id, parent.source_record_id, parent.source_url)
        child_identity = (event_id, source_record_id, source_url)
        if parent_identity != child_identity:
            raise ValueError("parent capture event/source lineage mismatch")
        if payload.get("parent_archive_sha256") != parent.sha256:
            raise ValueError("parent archive SHA-256 does not match verified parent capture")
        member_name = _required_text(payload, "member_name")
        member_crc32 = _required_text(payload, "member_crc32")
        if not re.fullmatch(r"[0-9a-f]{8}", member_crc32):
            raise ValueError("member_crc32 must be an eight-character lowercase hex value")
        try:
            with zipfile.ZipFile(parent.archive_path, "r") as package:
                infos = [
                    item
                    for item in package.infolist()
                    if item.filename == member_name and not item.is_dir()
                ]
                if len(infos) != 1:
                    raise ValueError("parent ZIP member is missing or duplicated")
                info = infos[0]
                member_digest = hashlib.sha256()
                member_length = 0
                with package.open(info, "r") as member_stream:
                    while chunk := member_stream.read(1024 * 1024):
                        member_digest.update(chunk)
                        member_length += len(chunk)
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise ValueError("cannot verify parent ZIP member lineage") from error
        member_matches = (
            member_length == actual_length
            and member_digest.hexdigest() == expected_sha256
            and f"{info.CRC:08x}" == member_crc32
        )
        if not member_matches:
            raise ValueError("child bytes do not match parent ZIP member lineage")
    return VerifiedCapture(
        manifest_path=manifest,
        archive_path=archive_path,
        event_id=event_id,
        source_record_id=source_record_id,
        source_url=source_url,
        document_type=document_type,
        byte_length=actual_length,
        sha256=expected_sha256,
        captured_at=captured_at,
    )
