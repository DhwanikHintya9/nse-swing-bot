"""Safely materialize one inventoried ZIP member with verifiable parent lineage."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from nse_swing_bot.events.capture_verification import verify_capture_manifest


def _safe_name(name: str) -> None:
    parts = name.split("/")
    path = PurePosixPath(name)
    if (
        not name or "\\" in name or path.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or any(":" in part for part in path.parts)
    ):
        raise ValueError(f"unsafe ZIP member path: {name!r}")


def _hash_stream(stream, output=None) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        length += len(chunk)
        if output is not None:
            output.write(chunk)
    return length, digest.hexdigest()


def materialize_verified_zip_member(
    capture_manifest_path: Path,
    inventory_manifest_path: Path,
    member_name: str,
    output_dir: Path,
    *,
    captured_at: datetime,
) -> Path:
    """Materialize one exact inventoried member; never extract the package."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    parent = verify_capture_manifest(capture_manifest_path)
    if parent.archive_path.suffix.lower() != ".zip":
        raise ValueError("parent capture must be a ZIP archive")
    inventory_path = inventory_manifest_path.expanduser().resolve(strict=True)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(inventory, dict) or inventory.get("schema_version") != 1:
        raise ValueError("unsupported ZIP inventory schema")
    if inventory.get("inventory_mode") != "captured_zip_read_only_no_extraction":
        raise ValueError("unsupported ZIP inventory mode")
    for key, expected in (
        ("event_id", parent.event_id),
        ("source_record_id", parent.source_record_id),
        ("source_url", parent.source_url),
        ("archive_sha256", parent.sha256),
        ("archive_byte_length", parent.byte_length),
        ("archive_filename", parent.archive_path.name),
    ):
        if inventory.get(key) != expected:
            raise ValueError(f"ZIP inventory {key} does not match verified parent capture")
    entries = inventory.get("members")
    if not isinstance(entries, list):
        raise ValueError("ZIP inventory members must be an array")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("name") == member_name
    ]
    if len(matches) != 1:
        raise ValueError("member must match exactly one inventory entry")
    entry = matches[0]
    _safe_name(member_name)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_dir.resolve()
    basename = re.sub(r"[^A-Za-z0-9._-]+", "_", PurePosixPath(member_name).name)[:100]
    if basename in {"", ".", ".."}:
        raise ValueError("ZIP member has no safe filename")
    temporary: Path | None = None
    try:
        with zipfile.ZipFile(parent.archive_path, "r") as package:
            infos = [
                info
                for info in package.infolist()
                if info.filename == member_name and not info.is_dir()
            ]
            if len(infos) != 1:
                raise ValueError("ZIP member is missing or duplicated in parent archive")
            info = infos[0]
            if info.flag_bits & 0x1:
                raise ValueError("encrypted ZIP member is not supported")
            if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                raise ValueError("symlink ZIP member is not supported")
            inventory_metadata_matches = (
                info.file_size == entry.get("byte_length")
                and f"{info.CRC:08x}" == entry.get("crc32")
            )
            if not inventory_metadata_matches:
                raise ValueError("ZIP member size or CRC does not match inventory")
            with package.open(info, "r") as source:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=output_root, prefix=".zip-member-", delete=False
                ) as target:
                    temporary = Path(target.name)
                    length, digest = _hash_stream(source, target)
                    target.flush()
                    os.fsync(target.fileno())
            if length != entry.get("byte_length") or digest != entry.get("sha256"):
                raise ValueError("ZIP member bytes do not match inventory length or SHA-256")
        destination = output_root / f"{parent.event_id}_{digest[:16]}_{basename}"
        manifest_path = output_root / f"{parent.event_id}_{digest[:16]}.member.capture.json"
        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise FileExistsError(
                f"refusing to overwrite ZIP member capture: {destination}"
            ) from None
        finally:
            temporary.unlink(missing_ok=True)
            temporary = None
        manifest = {
            "schema_version": 1,
            "event_id": parent.event_id,
            "source_record_id": parent.source_record_id,
            "source_url": parent.source_url,
            "document_type": "archive_member_" + (Path(basename).suffix.lstrip(".") or "file"),
            "original_filename": member_name,
            "archive_filename": destination.name,
            "byte_length": length,
            "sha256": digest,
            "captured_at": captured_at.isoformat(),
            "capture_mode": "zip_member_original_bytes_no_network",
            "parent_capture_manifest_path": str(parent.manifest_path),
            "parent_archive_sha256": parent.sha256,
            "member_name": member_name,
            "member_crc32": f"{info.CRC:08x}",
        }
        data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output_root, prefix=".member-manifest-", delete=False
        ) as stream:
            manifest_temp = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(manifest_temp, manifest_path)
        except FileExistsError:
            raise FileExistsError(
                f"refusing to overwrite ZIP member manifest: {manifest_path}"
            ) from None
        finally:
            manifest_temp.unlink(missing_ok=True)
        return manifest_path
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
