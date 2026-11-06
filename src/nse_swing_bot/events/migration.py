"""Explicit, auditable reconciliation for known legacy source-record aliases."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceIdAlias:
    canonical_event_id: str
    legacy_source_record_id: str
    resolved_source_record_id: str
    reason: str


def load_source_id_aliases(path: Path) -> list[SourceIdAlias]:
    required = {
        "canonical_event_id",
        "legacy_source_record_id",
        "resolved_source_record_id",
        "reason",
    }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = required.difference(reader.fieldnames or [])
            raise ValueError(f"alias file missing columns: {', '.join(sorted(missing))}")
        aliases: list[SourceIdAlias] = []
        seen_events: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            try:
                item = SourceIdAlias(
                    canonical_event_id=row["canonical_event_id"].strip(),
                    legacy_source_record_id=row["legacy_source_record_id"].strip(),
                    resolved_source_record_id=row["resolved_source_record_id"].strip(),
                    reason=row["reason"].strip(),
                )
                if not all(
                    (
                        item.canonical_event_id,
                        item.legacy_source_record_id,
                        item.resolved_source_record_id,
                        item.reason,
                    )
                ):
                    raise ValueError("all alias fields are required")
                if item.canonical_event_id in seen_events:
                    raise ValueError(f"duplicate canonical_event_id: {item.canonical_event_id}")
                seen_events.add(item.canonical_event_id)
                aliases.append(item)
            except (AttributeError, KeyError, ValueError) as error:
                raise ValueError(f"invalid alias row {row_number}: {error}") from error
    return aliases


def resolve_source_record_ids(
    canonical_source_ids: dict[str, str],
    triage_record_ids: set[str],
    aliases: list[SourceIdAlias],
) -> dict[str, str]:
    """Resolve exact IDs first, then explicitly reviewed event-specific aliases."""
    alias_by_event = {item.canonical_event_id: item for item in aliases}
    if len(alias_by_event) != len(aliases):
        raise ValueError("duplicate canonical event aliases")
    resolved: dict[str, str] = {}
    for event_id, source_id in canonical_source_ids.items():
        if source_id in triage_record_ids:
            resolved[event_id] = source_id
            continue
        alias = alias_by_event.get(event_id)
        if alias is None:
            raise ValueError(f"unresolved source record ID for {event_id}: {source_id}")
        if alias.legacy_source_record_id != source_id:
            raise ValueError(f"alias legacy ID mismatch for {event_id}")
        if alias.resolved_source_record_id not in triage_record_ids:
            raise ValueError(f"alias target is absent from triage for {event_id}")
        resolved[event_id] = alias.resolved_source_record_id
    unused = set(alias_by_event).difference(canonical_source_ids)
    if unused:
        raise ValueError("unused event aliases: " + ", ".join(sorted(unused)))
    return resolved
