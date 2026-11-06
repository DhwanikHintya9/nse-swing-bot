"""Point-in-time Nifty 500 snapshot evidence ingestion and conservative reconciliation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = 1
_REQUIRED_ALIASES = {
    "company_name": ("company name", "company_name", "name"),
    "industry": ("industry",),
    "symbol": ("symbol", "trading symbol", "tradingsymbol"),
    "series": ("series",),
    "isin": ("isin code", "isin", "isin_code"),
}
_ISIN_PATTERN = re.compile(r"^INE[A-Z0-9]{9}$")
_ALLOWED_SOURCE_KINDS = {"official_snapshot", "wayback_capture"}


class MembershipEvidenceError(ValueError):
    """Raised when a constituent snapshot lacks sufficient evidence or integrity."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_timestamp(value: str, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MembershipEvidenceError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise MembershipEvidenceError(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _is_official_nse_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower()
    return (
        host == "niftyindices.com"
        or host.endswith(".niftyindices.com")
        or host == "nseindia.com"
        or host.endswith(".nseindia.com")
    )


def _column_map(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise MembershipEvidenceError("snapshot CSV has no header")
    normalized = {name.strip().lower(): name for name in fieldnames}
    result: dict[str, str] = {}
    for target, aliases in _REQUIRED_ALIASES.items():
        match = next((normalized[alias] for alias in aliases if alias in normalized), None)
        if match is None:
            raise MembershipEvidenceError(
                f"snapshot CSV is missing required {target!r} column; "
                f"accepted headers: {', '.join(aliases)}"
            )
        result[target] = match
    return result


def _read_constituents(path: Path, min_rows: int, max_rows: int) -> list[dict[str, str]]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise MembershipEvidenceError(f"cannot read UTF-8 snapshot CSV: {error}") from error
    reader = csv.DictReader(text.splitlines())
    columns = _column_map(reader.fieldnames)
    rows: list[dict[str, str]] = []
    seen_isins: set[str] = set()
    for line_number, row in enumerate(reader, start=2):
        normalized = {
            key: (row.get(source) or "").strip()
            for key, source in columns.items()
        }
        normalized["symbol"] = normalized["symbol"].upper()
        normalized["series"] = normalized["series"].upper()
        normalized["isin"] = re.sub(r"\s+", "", normalized["isin"]).upper()
        if not all(normalized.values()):
            raise MembershipEvidenceError(f"blank required field on CSV line {line_number}")
        if not _ISIN_PATTERN.fullmatch(normalized["isin"]):
            raise MembershipEvidenceError(
                f"invalid Indian equity ISIN on CSV line {line_number}: {normalized['isin']}"
            )
        if normalized["isin"] in seen_isins:
            raise MembershipEvidenceError(f"duplicate ISIN in snapshot: {normalized['isin']}")
        seen_isins.add(normalized["isin"])
        rows.append(normalized)
    if not min_rows <= len(rows) <= max_rows:
        raise MembershipEvidenceError(
            f"snapshot row count {len(rows)} is outside configured bounds {min_rows}..{max_rows}"
        )
    return sorted(rows, key=lambda item: item["isin"])


def ingest_membership_snapshot(
    csv_path: Path,
    *,
    as_of_date: date,
    source_url: str,
    evidence_url: str,
    source_kind: str,
    captured_at_utc: str,
    published_at_utc: str | None,
    output_dir: Path,
    min_rows: int = 450,
    max_rows: int = 550,
) -> Path:
    """Validate a source CSV and write immutable normalized data plus evidence manifest."""
    if source_kind not in _ALLOWED_SOURCE_KINDS:
        raise MembershipEvidenceError(
            "source_kind must be official_snapshot or wayback_capture; "
            "third-party reconstructions are discovery-only"
        )
    if not source_url.startswith("https://") or not evidence_url.startswith("https://"):
        raise MembershipEvidenceError("source_url and evidence_url must use HTTPS")
    if not _is_official_nse_url(source_url):
        raise MembershipEvidenceError(
            "source_url must identify an official NSE/Nifty Indices source"
        )
    if source_kind == "official_snapshot" and not _is_official_nse_url(evidence_url):
        raise MembershipEvidenceError(
            "official_snapshot evidence_url must be on an official NSE domain"
        )
    if source_kind == "wayback_capture":
        host = (urlparse(evidence_url).hostname or "").lower()
        if host not in {"web.archive.org", "wayback.archive-it.org"}:
            raise MembershipEvidenceError(
                "wayback_capture evidence_url must be an archive replay URL"
            )
    captured = _utc_timestamp(captured_at_utc, "captured_at_utc")
    published = (
        _utc_timestamp(published_at_utc, "published_at_utc")
        if published_at_utc
        else None
    )
    raw_bytes = csv_path.read_bytes()
    rows = _read_constituents(csv_path, min_rows, max_rows)
    raw_sha256 = _sha256(raw_bytes)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"nifty500-{as_of_date.isoformat()}"
    normalized_path = output_dir / f"{stem}.csv"
    manifest_path = output_dir / f"{stem}.manifest.json"
    raw_dir = output_dir / "raw"
    raw_path = raw_dir / f"{as_of_date.isoformat()}-{raw_sha256[:12]}-{csv_path.name}"
    if normalized_path.exists() or manifest_path.exists() or raw_path.exists():
        raise FileExistsError(f"refusing to overwrite existing snapshot evidence for {as_of_date}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(csv_path, raw_path)

    with normalized_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["company_name", "industry", "symbol", "series", "isin"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    normalized_sha256 = _sha256(normalized_path.read_bytes())
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "index_name": "NIFTY 500",
        "as_of_date": as_of_date.isoformat(),
        "source_kind": source_kind,
        "source_url": source_url,
        "evidence_url": evidence_url,
        "published_at_utc": published,
        "captured_at_utc": captured,
        "raw_filename": str(raw_path.relative_to(output_dir)),
        "raw_sha256": raw_sha256,
        "normalized_filename": normalized_path.name,
        "normalized_sha256": normalized_sha256,
        "row_count": len(rows),
        "identity_key": "isin",
        "membership_semantics": "snapshot_observation_not_effective_interval",
        "effective_date_claimed": False,
        "third_party_data_used_as_anchor": False,
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest["manifest_sha256"] = _sha256(manifest_bytes)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _load_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MembershipEvidenceError(f"cannot read snapshot manifest {path}: {error}") from error
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("index_name") != "NIFTY 500"
    ):
        raise MembershipEvidenceError(f"unsupported membership manifest: {path}")
    supplied_hash = manifest.get("manifest_sha256")
    unhashed_manifest = dict(manifest)
    unhashed_manifest.pop("manifest_sha256", None)
    expected_manifest_hash = _sha256(
        json.dumps(
            unhashed_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    if supplied_hash != expected_manifest_hash:
        raise MembershipEvidenceError(f"manifest hash mismatch: {path}")
    raw_path = path.parent / str(manifest.get("raw_filename", ""))
    if not raw_path.is_file() or _sha256(raw_path.read_bytes()) != manifest.get("raw_sha256"):
        raise MembershipEvidenceError(f"raw source snapshot missing or hash mismatch: {path}")
    normalized_path = path.parent / str(manifest.get("normalized_filename", ""))
    if not normalized_path.is_file():
        raise MembershipEvidenceError(f"normalized snapshot missing for manifest: {path}")
    content = normalized_path.read_bytes()
    if _sha256(content) != manifest.get("normalized_sha256"):
        raise MembershipEvidenceError(f"normalized snapshot hash mismatch: {path}")
    with normalized_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != manifest.get("row_count"):
        raise MembershipEvidenceError(f"snapshot row count mismatch: {path}")
    if len({row["isin"] for row in rows}) != len(rows):
        raise MembershipEvidenceError(f"duplicate ISIN in normalized snapshot: {path}")
    return manifest, rows


def reconcile_membership_snapshots(snapshot_dir: Path, output_csv: Path) -> dict[str, Any]:
    """Diff adjacent snapshots by ISIN; never infer an exact membership effective date."""
    manifests = sorted(snapshot_dir.glob("*.manifest.json"))
    if len(manifests) < 2:
        raise MembershipEvidenceError("at least two independently dated snapshots are required")
    loaded = [_load_manifest(path) for path in manifests]
    loaded.sort(key=lambda pair: pair[0]["as_of_date"])
    dates = [pair[0]["as_of_date"] for pair in loaded]
    if len(set(dates)) != len(dates):
        raise MembershipEvidenceError("multiple snapshots share the same as_of_date")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    diff_rows: list[dict[str, str]] = []
    intervals: list[dict[str, Any]] = []
    for (before_manifest, before_rows), (after_manifest, after_rows) in zip(
        loaded, loaded[1:], strict=False
    ):
        before = {row["isin"]: row for row in before_rows}
        after = {row["isin"]: row for row in after_rows}
        added = sorted(after.keys() - before.keys())
        removed = sorted(before.keys() - after.keys())
        for change, identifiers, old, new in (
            ("observed_addition", added, before, after),
            ("observed_removal", removed, before, after),
        ):
            for isin in identifiers:
                prior = old.get(isin, {})
                current = new.get(isin, {})
                diff_rows.append(
                    {
                        "isin": isin,
                        "change": change,
                        "previous_snapshot_date": before_manifest["as_of_date"],
                        "next_snapshot_date": after_manifest["as_of_date"],
                        "previous_symbol": prior.get("symbol", ""),
                        "next_symbol": current.get("symbol", ""),
                        "previous_company_name": prior.get("company_name", ""),
                        "next_company_name": current.get("company_name", ""),
                        "effective_date": "",
                        "effective_date_status": "unknown_between_snapshots",
                        "evidence_before_manifest": Path(
                            str(before_manifest["normalized_filename"])
                        ).with_suffix(".manifest.json").name,
                        "evidence_after_manifest": Path(
                            str(after_manifest["normalized_filename"])
                        ).with_suffix(".manifest.json").name,
                    }
                )
        intervals.append(
            {
                "previous_snapshot_date": before_manifest["as_of_date"],
                "next_snapshot_date": after_manifest["as_of_date"],
                "previous_row_count": len(before),
                "next_row_count": len(after),
                "observed_additions": len(added),
                "observed_removals": len(removed),
                "unexplained_changes": len(added) + len(removed),
                "effective_dates_inferred": False,
            }
        )
    fieldnames = [
        "isin", "change", "previous_snapshot_date", "next_snapshot_date",
        "previous_symbol", "next_symbol", "previous_company_name",
        "next_company_name", "effective_date", "effective_date_status",
        "evidence_before_manifest", "evidence_after_manifest",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(diff_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "index_name": "NIFTY 500",
        "snapshot_count": len(loaded),
        "first_snapshot_date": dates[0],
        "last_snapshot_date": dates[-1],
        "intervals": intervals,
        "diff_csv": str(output_csv),
        "total_observed_changes": len(diff_rows),
        "effective_dates_inferred": False,
        "research_ready": False,
        "limitations": [
            "Snapshot differences only bound a change between two observation dates.",
            "They do not establish the exact effective date.",
            "Unobserved intermediate changes may cancel out between snapshots.",
            "ISIN migrations, mergers and demergers require separate identity-chain evidence.",
            "Press releases resolve a change date only when explicitly supported by the notice.",
        ],
    }
