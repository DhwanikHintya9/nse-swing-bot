"""Immutable local capture of original exchange/issuer source bytes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class CapturedSource:
    event_id: str
    source_record_id: str
    source_url: str
    document_type: str
    original_filename: str
    archive_path: Path
    manifest_path: Path
    byte_length: int
    sha256: str
    captured_at: datetime


def _validate_identifier(value: str, field: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        raise ValueError(f"{field} must contain only letters, numbers, dot, underscore or hyphen")


def _validate_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be an absolute HTTP(S) URL")


def _validate_time(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")


def _copy_and_hash(source: Path, destination_dir: Path) -> tuple[Path, int, str]:
    digest = hashlib.sha256()
    byte_length = 0
    temporary_path: Path | None = None
    try:
        with source.open("rb") as source_stream:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination_dir, prefix=".capture-", delete=False
            ) as output_stream:
                temporary_path = Path(output_stream.name)
                while chunk := source_stream.read(1024 * 1024):
                    output_stream.write(chunk)
                    digest.update(chunk)
                    byte_length += len(chunk)
                output_stream.flush()
                os.fsync(output_stream.fileno())
        return temporary_path, byte_length, digest.hexdigest()
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _publish_immutable(temporary_path: Path, destination: Path) -> None:
    try:
        os.link(temporary_path, destination)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite existing capture: {destination}") from None
    finally:
        temporary_path.unlink(missing_ok=True)


def capture_source_bytes(
    source_path: Path,
    archive_dir: Path,
    *,
    event_id: str,
    source_record_id: str,
    source_url: str,
    document_type: str,
    captured_at: datetime,
) -> CapturedSource:
    """Copy source bytes into an immutable archive and write a SHA-256 manifest.

    The function never downloads a URL and never modifies the input file.
    Existing archive or manifest paths are never overwritten.
    """
    _validate_identifier(event_id, "event_id")
    _validate_identifier(source_record_id, "source_record_id")
    if not document_type.strip():
        raise ValueError("document_type is required")
    _validate_url(source_url)
    _validate_time(captured_at)

    source = source_path.expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("source_path must identify a regular file")
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_root = archive_dir.resolve()
    temporary_path, byte_length, sha256 = _copy_and_hash(source, archive_root)
    suffix = source.suffix.lower()
    archive_path = archive_root / f"{event_id}_{sha256[:16]}{suffix}"
    manifest_path = archive_root / f"{event_id}_{sha256[:16]}.capture.json"

    try:
        _publish_immutable(temporary_path, archive_path)
        manifest = {
            "schema_version": 1,
            "event_id": event_id,
            "source_record_id": source_record_id,
            "source_url": source_url,
            "document_type": document_type.strip(),
            "original_filename": source.name,
            "archive_filename": archive_path.name,
            "byte_length": byte_length,
            "sha256": sha256,
            "captured_at": captured_at.isoformat(),
            "capture_mode": "local_original_bytes_no_network",
        }
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=archive_root, prefix=".manifest-", delete=False
        ) as output_stream:
            manifest_temp = Path(output_stream.name)
            output_stream.write(manifest_bytes)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        _publish_immutable(manifest_temp, manifest_path)
    except Exception:
        # Do not remove an already published immutable source if manifest writing fails.
        raise

    return CapturedSource(
        event_id=event_id,
        source_record_id=source_record_id,
        source_url=source_url,
        document_type=document_type.strip(),
        original_filename=source.name,
        archive_path=archive_path,
        manifest_path=manifest_path,
        byte_length=byte_length,
        sha256=sha256,
        captured_at=captured_at,
    )
