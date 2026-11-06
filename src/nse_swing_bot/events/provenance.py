"""Read-only ingestion of operator-authored event evidence manifests."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nse_swing_bot.events.capture_verification import VerifiedCapture, verify_capture_manifest
from nse_swing_bot.events.evidence import (
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceTier,
)


@dataclass(frozen=True)
class EvidenceFactLink:
    event_id: str
    fact_name: str
    evidence_id: str
    page_number: int
    exact_excerpt: str


@dataclass(frozen=True)
class EvidenceIngestionBundle:
    evidence_records: tuple[EvidenceRecord, ...]
    fact_links: tuple[EvidenceFactLink, ...]
    required_fact_evidence: dict[str, dict[str, tuple[str, ...]]]
    document_types: dict[str, str]
    source_record_ids: dict[str, str]
    material_attachment_names: dict[str, tuple[str, ...]]


def _text(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _time(value: Any, field: str, optional: bool = False) -> datetime | None:
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset")
    return parsed


def _string_list(item: dict[str, Any], field: str) -> tuple[str, ...]:
    value = item.get(field, [])
    if not isinstance(value, list) or any(
        not isinstance(part, str) or not part.strip() for part in value
    ):
        raise ValueError(f"{field} must be an array of non-empty strings")
    return tuple(part.strip() for part in value)


def load_evidence_manifest(
    path: Path, expected_event_sources: dict[str, str]
) -> EvidenceIngestionBundle:
    """Validate document provenance and fact-level links against migrated event IDs."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported evidence manifest schema_version")
    documents, links = payload.get("documents"), payload.get("fact_links")
    if not isinstance(documents, list) or not isinstance(links, list):
        raise ValueError("documents and fact_links must be arrays")

    records: list[EvidenceRecord] = []
    by_id: dict[str, EvidenceRecord] = {}
    document_types: dict[str, str] = {}
    source_ids: dict[str, str] = {}
    attachment_names: dict[str, tuple[str, ...]] = {}
    for item in documents:
        if not isinstance(item, dict):
            raise ValueError("each document must be an object")
        evidence_id, event_id = _text(item, "evidence_id"), _text(item, "event_id")
        source_id = _text(item, "source_record_id")
        document_type = _text(item, "document_type")
        if event_id not in expected_event_sources:
            raise ValueError(f"unknown canonical event: {event_id}")
        if expected_event_sources[event_id] != source_id:
            raise ValueError(f"source record mismatch for event {event_id}")
        if evidence_id in by_id:
            raise ValueError(f"duplicate evidence_id: {evidence_id}")
        try:
            tier = EvidenceTier(_text(item, "source_tier"))
            status = EvidenceReviewStatus(_text(item, "review_status"))
        except ValueError as error:
            raise ValueError(f"invalid evidence classification for {evidence_id}") from error

        required_attachments = item.get("material_attachments_required") is True
        names = _string_list(item, "material_attachment_names")
        reviewed_names = _string_list(item, "reviewed_material_attachment_names")
        if len(names) != len(set(names)) or len(reviewed_names) != len(set(reviewed_names)):
            raise ValueError(f"duplicate material attachment name for {evidence_id}")
        if not set(reviewed_names).issubset(names):
            raise ValueError(f"reviewed attachment not declared for {evidence_id}")
        all_reviewed = bool(names) and set(names) == set(reviewed_names)
        if required_attachments and names and not all_reviewed:
            raise ValueError(f"material attachments are not fully reviewed for {evidence_id}")

        retrieved_at = _time(item.get("retrieved_at"), "retrieved_at")
        if retrieved_at is None:
            raise ValueError(f"retrieved_at is required for {evidence_id}")
        record = EvidenceRecord(
            evidence_id=evidence_id,
            event_id=event_id,
            source_tier=tier,
            review_status=status,
            source_url=_text(item, "source_url"),
            retrieved_at=retrieved_at,
            published_at=_time(item.get("published_at"), "published_at", optional=True),
            content_sha256=item.get("content_sha256"),
            original_document=item.get("original_document") is True,
            directly_reviewed=item.get("directly_reviewed") is True,
            material_attachments_required=required_attachments,
            material_attachments_reviewed=(not required_attachments or all_reviewed)
            and item.get("material_attachments_reviewed") is True,
            exact_excerpt=_text(item, "document_excerpt"),
        )
        by_id[evidence_id] = record
        records.append(record)
        document_types[evidence_id] = document_type
        source_ids[evidence_id] = source_id
        attachment_names[evidence_id] = names

    fact_links: list[EvidenceFactLink] = []
    required: dict[str, dict[str, list[str]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for item in links:
        if not isinstance(item, dict):
            raise ValueError("each fact link must be an object")
        event_id, fact = _text(item, "event_id"), _text(item, "fact_name")
        evidence_id, excerpt = _text(item, "evidence_id"), _text(item, "exact_excerpt")
        page = item.get("page_number")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError(f"page_number must be a positive integer for {evidence_id}")
        record = by_id.get(evidence_id)
        if record is None:
            raise ValueError(f"unknown evidence_id: {evidence_id}")
        if record.event_id != event_id:
            raise ValueError(f"fact link event mismatch for evidence {evidence_id}")
        key = (event_id, fact, evidence_id)
        if key in seen:
            raise ValueError(f"duplicate fact link: {key}")
        seen.add(key)
        fact_links.append(EvidenceFactLink(event_id, fact, evidence_id, page, excerpt))
        required.setdefault(event_id, {}).setdefault(fact, []).append(evidence_id)

    return EvidenceIngestionBundle(
        evidence_records=tuple(records),
        fact_links=tuple(fact_links),
        required_fact_evidence={
            event: {fact: tuple(ids) for fact, ids in facts.items()}
            for event, facts in required.items()
        },
        document_types=document_types,
        source_record_ids=source_ids,
        material_attachment_names=attachment_names,
    )


@dataclass(frozen=True)
class VerifiedEvidenceIngestion:
    """Evidence bundle with verified local capture lineage for every P1 document."""

    bundle: EvidenceIngestionBundle
    verified_captures: dict[str, VerifiedCapture]


def load_verified_evidence_manifest(
    path: Path,
    expected_event_sources: dict[str, str],
    capture_manifests: dict[str, Path],
) -> VerifiedEvidenceIngestion:
    """Load provenance and bind P1 evidence to verified local capture bytes.

    Each P1 evidence_id must have a capture manifest. Event ID, Stage 3C source
    record ID, source URL, document type and SHA-256 must match exactly. For
    non-P1 evidence, a supplied capture manifest is verified and cross-checked
    too; no capture is required for research-only references.
    """
    bundle = load_evidence_manifest(path, expected_event_sources)
    documents_payload = json.loads(path.read_text(encoding="utf-8"))
    documents = {
        item["evidence_id"]: item
        for item in documents_payload["documents"]
    }
    known_ids = {record.evidence_id for record in bundle.evidence_records}
    unknown_capture_ids = set(capture_manifests) - known_ids
    if unknown_capture_ids:
        raise ValueError(
            "capture manifests reference unknown evidence IDs: "
            + ", ".join(sorted(unknown_capture_ids))
        )

    verified: dict[str, VerifiedCapture] = {}
    for record in bundle.evidence_records:
        capture_path = capture_manifests.get(record.evidence_id)
        if capture_path is None:
            if record.source_tier == EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED:
                raise ValueError(
                    f"missing verified capture manifest for P1 evidence {record.evidence_id}"
                )
            continue
        capture = verify_capture_manifest(capture_path)
        document = documents[record.evidence_id]
        expected = {
            "event_id": record.event_id,
            "source_record_id": bundle.source_record_ids[record.evidence_id],
            "source_url": record.source_url,
            "document_type": bundle.document_types[record.evidence_id],
            "sha256": record.content_sha256,
        }
        actual = {
            "event_id": capture.event_id,
            "source_record_id": capture.source_record_id,
            "source_url": capture.source_url,
            "document_type": capture.document_type,
            "sha256": capture.sha256,
        }
        for field, expected_value in expected.items():
            if expected_value != actual[field]:
                raise ValueError(
                    f"capture {field} mismatch for evidence {record.evidence_id}"
                )
        if document.get("original_document") is True and not record.original_document:
            raise ValueError(f"original-document flag mismatch for {record.evidence_id}")
        verified[record.evidence_id] = capture

    return VerifiedEvidenceIngestion(bundle=bundle, verified_captures=verified)
