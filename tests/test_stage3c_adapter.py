from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from nse_swing_bot.events.stage3c_adapter import (
    migrate_stage3c_files,
    write_stage3c_migration_snapshot,
)

CAPTURED = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _write_inputs(tmp_path: Path):
    triage = tmp_path / "triage.csv"
    triage.write_text(
        "record_id,symbol,review_status,verification_status,research_triage\n"
        "record-1,ABC,pending,primary_source_verified,reviewed\n"
        "record-2,XYZ,pending,secondary_corroborated,quarantined\n",
        encoding="utf-8",
    )
    events = tmp_path / "events.csv"
    events.write_text(
        "canonical_event_id,symbol,event_date,event_description,event_status,"
        "evidence_basis,source_record_id\n"
        "EV-ABC-01,ABC,2026-11-04,Appointment,Announced,Original PDF reviewed,record-1\n"
        "EV-XYZ-01,XYZ,2026-11-05,Acquisition,Proposed,Secondary mirror,record-2\n",
        encoding="utf-8",
    )
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "symbol,queue_status,resolution_or_blocker,eligible_for_signal_pipeline\n"
        "ABC,resolved,Primary PDF reviewed,False\n"
        "XYZ,partial_quarantine,Primary attachment open,False\n",
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "canonical_event_id,legacy_source_record_id,resolved_source_record_id,reason\n",
        encoding="utf-8",
    )
    return triage, events, queue, aliases


def test_stage3c_adapter_preserves_source_rows_and_never_promotes(tmp_path):
    triage, events, queue, aliases = _write_inputs(tmp_path)
    before = {path: path.read_bytes() for path in (triage, events, queue, aliases)}
    snapshot = migrate_stage3c_files(triage, events, queue, aliases, CAPTURED)
    payload = snapshot.to_dict()

    assert len(payload["triage_rows"]) == 2
    assert len(payload["canonical_events"]) == 2
    assert len(payload["queue_rows"]) == 2
    assert payload["triage_rows"][0]["review_status"] == "pending"
    assert payload["triage_rows"][0]["verification_status"] == "primary_source_verified"
    assert payload["canonical_events"][0]["legacy_source_record_id"] == "record-1"
    assert payload["canonical_events"][0]["resolved_source_record_id"] == "record-1"
    assert payload["canonical_events"][0]["production_eligible"] is False
    assert payload["canonical_events"][0]["evidence_admission"] == "not_evaluated"
    assert payload["canonical_events"][1]["queue_status"] == "partial_quarantine"
    assert all(item["production_eligible"] is False for item in payload["canonical_events"])
    assert {path: path.read_bytes() for path in before} == before


def test_stage3c_adapter_resolves_only_explicit_aliases(tmp_path):
    triage, events, queue, aliases = _write_inputs(tmp_path)
    # Replace one event's source ID with a known legacy value and supply an exact alias.
    text = events.read_text(encoding="utf-8").replace("record-1\n", "legacy-1\n", 1)
    events.write_text(text, encoding="utf-8")
    aliases.write_text(
        "canonical_event_id,legacy_source_record_id,resolved_source_record_id,reason\n"
        "EV-ABC-01,legacy-1,record-1,Reviewed one-to-one mapping\n",
        encoding="utf-8",
    )
    snapshot = migrate_stage3c_files(triage, events, queue, aliases, CAPTURED)
    item = snapshot.to_dict()["canonical_events"][0]
    assert item["legacy_source_record_id"] == "legacy-1"
    assert item["resolved_source_record_id"] == "record-1"
    assert item["source_id_resolution"] == "explicit_alias"
    assert item["source_id_alias_reason"] == "Reviewed one-to-one mapping"


def test_stage3c_adapter_rejects_unmapped_source_ids(tmp_path):
    triage, events, queue, aliases = _write_inputs(tmp_path)
    events.write_text(
        events.read_text(encoding="utf-8").replace("record-1", "unknown-id"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unresolved source record ID"):
        migrate_stage3c_files(triage, events, queue, aliases, CAPTURED)


def test_stage3c_adapter_rejects_cross_symbol_source_links(tmp_path):
    triage, events, queue, aliases = _write_inputs(tmp_path)
    events.write_text(
        events.read_text(encoding="utf-8").replace("ABC,2026-11-04", "XYZ,2026-11-04"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="symbol mismatch"):
        migrate_stage3c_files(triage, events, queue, aliases, CAPTURED)


def test_stage3c_adapter_rejects_duplicate_triage_ids(tmp_path):
    triage, events, queue, aliases = _write_inputs(tmp_path)
    triage.write_text(
        triage.read_text(encoding="utf-8") + "record-1,ABC,pending,pending,duplicate\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate record_id"):
        migrate_stage3c_files(triage, events, queue, aliases, CAPTURED)


def test_stage3c_adapter_rejects_duplicate_canonical_event_ids(tmp_path):
    triage, events, queue, aliases = _write_inputs(tmp_path)
    events.write_text(
        events.read_text(encoding="utf-8")
        + "EV-ABC-01,ABC,2026-11-06,Duplicate,Proposed,Test,record-1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate canonical_event_id"):
        migrate_stage3c_files(triage, events, queue, aliases, CAPTURED)


def test_stage3c_snapshot_is_immutable_and_keeps_input_hashes(tmp_path):
    triage, events, queue, aliases = _write_inputs(tmp_path)
    snapshot = migrate_stage3c_files(triage, events, queue, aliases, CAPTURED)
    output = write_stage3c_migration_snapshot(snapshot, tmp_path / "out")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["migration_mode"] == "read_only_preserve_source"
    assert payload["production_eligible"] is False
    assert len(payload["inputs"]) == 4
    assert all(len(item["sha256"]) == 64 for item in payload["inputs"])
    assert output.exists()
