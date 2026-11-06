"""Read-only ingestion of operator-authored event evidence manifests."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nse_swing_bot.events.evidence import EvidenceRecord, EvidenceReviewStatus, EvidenceTier


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
    for item in documents:
        if not isinstance(item, dict):
            raise ValueError("each document must be an object")
        evidence_id, event_id = _text(item, "evidence_id"), _text(item, "event_id")
        source_id = _text(item, "source_record_id")
        _text(item, "document_type")
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
        record = EvidenceRecord(
            evidence_id=evidence_id,
            event_id=event_id,
            source_tier=tier,
            review_status=status,
            source_url=_text(item, "source_url"),
            retrieved_at=_time(item.get("retrieved_at"), "retrieved_at"),
            published_at=_time(item.get("published_at"), "published_at", optional=True),
            content_sha256=item.get("content_sha256"),
            original_document=item.get("original_document") is True,
            directly_reviewed=item.get("directly_reviewed") is True,
            material_attachments_required=item.get("material_attachments_required") is True,
            material_attachments_reviewed=item.get("material_attachments_reviewed") is True,
            exact_excerpt=_text(item, "document_excerpt"),
        )
        by_id[evidence_id] = record
        records.append(record)

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
        tuple(records),
        tuple(fact_links),
        {event: {fact: tuple(ids) for fact, ids in facts.items()} for event, facts in required.items()},
    )
