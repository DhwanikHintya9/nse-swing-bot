"""Safe, non-extracting inventory of captured ZIP filing packages."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from nse_swing_bot.events.capture_verification import (
    VerifiedCapture,
    verify_capture_manifest,
)


@dataclass(frozen=True)
class ZipMember:
    name: str
    byte_length: int
    compressed_byte_length: int
    crc32: str
    sha256: str


@dataclass(frozen=True)
class ZipPackageInventory:
    manifest_path: Path
    event_id: str
    source_record_id: str
    archive_sha256: str
    member_count: int
    total_uncompressed_bytes: int
    members: tuple[ZipMember, ...]


def _safe_member_name(name: str) -> None:
    if not name or "\\" in name:
        raise ValueError(f"unsafe ZIP member path: {name!r}")
    normalized_name = name[:-1] if name.endswith("/") else name
    raw_parts = normalized_name.split("/")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe ZIP member path: {name!r}")
    if any(":" in part for part in path.parts):
        raise ValueError(f"unsafe ZIP member path: {name!r}")


def _hash_member(package: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with package.open(info, "r") as member:
        while chunk := member.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_manifest(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".zip-inventory-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise FileExistsError(f"refusing to overwrite ZIP inventory: {path}") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def inspect_captured_zip_package(
    capture_manifest_path: Path,
    inventory_manifest_path: Path,
    *,
    max_members: int = 500,
    max_member_bytes: int = 100 * 1024 * 1024,
    max_total_uncompressed_bytes: int = 200 * 1024 * 1024,
    max_compression_ratio: int = 1000,
) -> ZipPackageInventory:
    """Inventory and hash ZIP members without extracting any content.

    The parent capture manifest is re-verified first. Member names, duplicates,
    symlinks, encryption and decompression limits are checked before member data
    is read. The output binds each member digest to the parent archive digest.
    This does not establish issuer authenticity or human review.
    """
    for field, value in (
        ("max_members", max_members),
        ("max_member_bytes", max_member_bytes),
        ("max_total_uncompressed_bytes", max_total_uncompressed_bytes),
        ("max_compression_ratio", max_compression_ratio),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{field} must be a positive integer")

    capture: VerifiedCapture = verify_capture_manifest(capture_manifest_path)
    if capture.archive_path.suffix.lower() != ".zip":
        raise ValueError("captured source must have a .zip extension")
    try:
        package = zipfile.ZipFile(capture.archive_path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("captured source is not a readable ZIP package") from error

    members: list[ZipMember] = []
    seen_names: set[str] = set()
    total_bytes = 0
    with package:
        infos = package.infolist()
        if len(infos) > max_members:
            raise ValueError("ZIP member count exceeds configured limit")
        for info in infos:
            _safe_member_name(info.filename)
            if info.filename in seen_names:
                raise ValueError(f"duplicate ZIP member name: {info.filename}")
            seen_names.add(info.filename)
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                raise ValueError(f"encrypted ZIP member is not supported: {info.filename}")
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode):
                raise ValueError(f"symlink ZIP member is not supported: {info.filename}")
            if info.file_size < 0 or info.compress_size < 0:
                raise ValueError(f"invalid ZIP member size: {info.filename}")
            if info.file_size > max_member_bytes:
                raise ValueError(f"ZIP member exceeds configured size limit: {info.filename}")
            total_bytes += info.file_size
            if total_bytes > max_total_uncompressed_bytes:
                raise ValueError("ZIP total uncompressed size exceeds configured limit")
            if info.file_size and info.compress_size == 0:
                raise ValueError(f"invalid compressed size: {info.filename}")
            if info.compress_size and info.file_size / info.compress_size > max_compression_ratio:
                raise ValueError(f"ZIP compression ratio exceeds configured limit: {info.filename}")
            try:
                member_sha256 = _hash_member(package, info)
            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as error:
                raise ValueError(f"cannot read ZIP member: {info.filename}") from error
            members.append(
                ZipMember(
                    name=info.filename,
                    byte_length=info.file_size,
                    compressed_byte_length=info.compress_size,
                    crc32=f"{info.CRC:08x}",
                    sha256=member_sha256,
                )
            )

    payload: dict[str, object] = {
        "schema_version": 1,
        "inventory_mode": "captured_zip_read_only_no_extraction",
        "event_id": capture.event_id,
        "source_record_id": capture.source_record_id,
        "source_url": capture.source_url,
        "archive_filename": capture.archive_path.name,
        "archive_sha256": capture.sha256,
        "archive_byte_length": capture.byte_length,
        "member_count": len(members),
        "total_uncompressed_bytes": total_bytes,
        "members": [asdict(member) for member in members],
    }
    _publish_manifest(inventory_manifest_path, payload)
    return ZipPackageInventory(
        manifest_path=inventory_manifest_path,
        event_id=capture.event_id,
        source_record_id=capture.source_record_id,
        archive_sha256=capture.sha256,
        member_count=len(members),
        total_uncompressed_bytes=total_bytes,
        members=tuple(members),
    )
