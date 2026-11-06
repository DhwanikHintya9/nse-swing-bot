"""Read-only adapter for the Stage 3C research-triage artifacts.

All source CSV cells are retained verbatim. The adapter adds explicit linkage
metadata but does not alter review status, infer verification tiers, or admit
any migrated event to the signal pipeline.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from nse_swing_bot.events.migration import load_source_id_aliases, resolve_source_record_ids


@dataclass(frozen=True)
class InputManifest:
    filename: str
    sha256: str
    row_count: int
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Stage3CMigrationSnapshot:
    captured_at: datetime
    triage_rows: tuple[dict[str, str], ...]
    canonical_events: tuple[dict[str, object], ...]
    queue_rows: tuple[dict[str, str], ...]
    aliases: tuple[dict[str, str], ...]
    inputs: tuple[InputManifest, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "migration_mode": "read_only_preserve_source",
            "captured_at": self.captured_at.isoformat(),
            "production_eligible": False,
            "evidence_admission": "not_evaluated",
            "counts": {
                "triage_rows": len(self.triage_rows),
                "canonical_events": len(self.canonical_events),
                "queue_rows": len(self.queue_rows),
                "source_id_aliases": len(self.aliases),
                "canonical_events_with_exact_source_id": sum(
                    item["source_id_resolution"] == "exact"
                    for item in self.canonical_events
                ),
                "canonical_events_with_explicit_alias": sum(
                    item["source_id_resolution"] == "explicit_alias"
                    for item in self.canonical_events
                ),
            },
            "inputs": [asdict(item) for item in self.inputs],
            "triage_rows": list(self.triage_rows),
            "canonical_events": list(self.canonical_events),
            "queue_rows": list(self.queue_rows),
            "aliases": list(self.aliases),
        }


def _read_csv(path: Path, required: set[str]) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        if not columns or not required.issubset(columns):
            missing = required.difference(columns)
            raise ValueError(f"{path.name}: missing required columns: {', '.join(sorted(missing))}")
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"{path.name}: row {row_number} has extra CSV fields")
            if any(value is None for value in row.values()):
                raise ValueError(f"{path.name}: row {row_number} has missing CSV fields")
            rows.append({key: value for key, value in row.items()})
    return rows, columns


def _manifest(path: Path, rows: list[dict[str, str]], columns: tuple[str, ...]) -> InputManifest:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return InputManifest(
        filename=path.name,
        sha256=digest,
        row_count=len(rows),
        columns=columns,
    )


def migrate_stage3c_files(
    triage_path: Path,
    canonical_events_path: Path,
    queue_path: Path,
    aliases_path: Path,
    captured_at: datetime,
) -> Stage3CMigrationSnapshot:
    """Load Stage 3C CSVs without editing them and create an auditable linkage view."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")

    triage, triage_columns = _read_csv(
        triage_path, {"record_id", "symbol", "review_status", "verification_status"}
    )
    canonical, event_columns = _read_csv(
        canonical_events_path,
        {
            "canonical_event_id",
            "symbol",
            "event_date",
            "event_description",
            "event_status",
            "evidence_basis",
            "source_record_id",
        },
    )
    queue, queue_columns = _read_csv(
        queue_path,
        {"symbol", "queue_status", "eligible_for_signal_pipeline", "resolution_or_blocker"},
    )
    aliases = load_source_id_aliases(aliases_path)

    triage_ids = [row["record_id"] for row in triage]
    event_ids = [row["canonical_event_id"] for row in canonical]
    queue_symbols = [row["symbol"] for row in queue]
    if any(not value.strip() for value in triage_ids + event_ids + queue_symbols):
        raise ValueError("Stage 3C inputs contain blank primary identifiers")
    if len(triage_ids) != len(set(triage_ids)):
        raise ValueError("triage CSV contains duplicate record_id values")
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("canonical event CSV contains duplicate canonical_event_id values")
    if len(queue_symbols) != len(set(queue_symbols)):
        raise ValueError("open queue CSV contains duplicate symbols")

    triage_by_id = {row["record_id"]: row for row in triage}
    queue_by_symbol = {row["symbol"]: row for row in queue}
    source_ids = {row["canonical_event_id"]: row["source_record_id"] for row in canonical}
    resolved_ids = resolve_source_record_ids(source_ids, set(triage_ids), aliases)

    migrated_events: list[dict[str, object]] = []
    alias_by_event = {item.canonical_event_id: item for item in aliases}
    for row in canonical:
        event_id = row["canonical_event_id"]
        original_id = row["source_record_id"]
        resolved_id = resolved_ids[event_id]
        triage_row = triage_by_id[resolved_id]
        if triage_row["symbol"].strip().upper() != row["symbol"].strip().upper():
            raise ValueError(
                f"symbol mismatch for {event_id}: canonical={row['symbol']} "
                f"triage={triage_row['symbol']}"
            )
        alias = alias_by_event.get(event_id)
        migrated_events.append(
            {
                "canonical_event_id": event_id,
                "symbol": row["symbol"],
                "legacy_source_record_id": original_id,
                "resolved_source_record_id": resolved_id,
                "source_id_resolution": "explicit_alias" if alias else "exact",
                "source_id_alias_reason": alias.reason if alias else "",
                "triage_review_status": triage_row["review_status"],
                "triage_verification_status": triage_row["verification_status"],
                "triage_research_triage": triage_row.get("research_triage", ""),
                "queue_status": queue_by_symbol.get(row["symbol"], {}).get("queue_status", ""),
                "legacy_queue_eligible_for_signal_pipeline": queue_by_symbol.get(
                    row["symbol"], {}
                ).get("eligible_for_signal_pipeline", ""),
                "production_eligible": False,
                "evidence_admission": "not_evaluated",
                "canonical_event_source_fields": row,
            }
        )

    return Stage3CMigrationSnapshot(
        captured_at=captured_at,
        triage_rows=tuple(triage),
        canonical_events=tuple(migrated_events),
        queue_rows=tuple(queue),
        aliases=tuple(asdict(item) for item in aliases),
        inputs=(
            _manifest(triage_path, triage, triage_columns),
            _manifest(canonical_events_path, canonical, event_columns),
            _manifest(queue_path, queue, queue_columns),
            InputManifest(
                filename=aliases_path.name,
                sha256=hashlib.sha256(aliases_path.read_bytes()).hexdigest(),
                row_count=len(aliases),
                columns=(
                    "canonical_event_id",
                    "legacy_source_record_id",
                    "resolved_source_record_id",
                    "reason",
                ),
            ),
        ),
    )


def write_stage3c_migration_snapshot(
    snapshot: Stage3CMigrationSnapshot,
    output_dir: Path,
) -> Path:
    """Persist a new immutable JSON snapshot; never overwrite an existing file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = snapshot.captured_at.strftime("%Y%m%dT%H%M%S%f%z")
    output = output_dir / f"stage3c-migration-{timestamp}-{uuid4().hex[:8]}.json"
    descriptor, temporary = tempfile.mkstemp(prefix=".stage3c-migration-", dir=output_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(snapshot.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    Path(temporary).unlink(missing_ok=True)
    return output
