"""Operator review manifests bound to verified corporate-event source bytes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nse_swing_bot.events.evidence import EvidenceReviewStatus, EvidenceTier
from nse_swing_bot.events.provenance import (
    VerifiedEvidenceIngestion,
    load_verified_evidence_manifest,
)


@dataclass(frozen=True)
class ReviewedFact:
    fact_name: str
    page_number: int
    exact_excerpt: str


@dataclass(frozen=True)
class DocumentReview:
    evidence_id: str
    event_id: str
    source_record_id: str
    source_url: str
    document_type: str
    content_sha256: str
    reviewer_id: str
    reviewer_role: str
    reviewed_at: datetime
    review_status: EvidenceReviewStatus
    source_identity_verified: bool
    original_document_confirmed: bool
    page_count: int
    attachment_inventory: tuple[str, ...]
    reviewed_attachments: tuple[str, ...]
    fact_reviews: tuple[ReviewedFact, ...]


@dataclass(frozen=True)
class EvidenceReviewIngestion:
    verified_evidence: VerifiedEvidenceIngestion
    document_reviews: tuple[DocumentReview, ...]

    @property
    def accepted_evidence_ids(self) -> tuple[str, ...]:
        """P1 documents whose operator review is accepted and complete."""
        return tuple(
            review.evidence_id
            for review in self.document_reviews
            if review.review_status == EvidenceReviewStatus.ACCEPTED
        )


def _required_text(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _aware_time(value: Any, field: str) -> datetime:
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
    value = item.get(field)
    if not isinstance(value, list) or any(
        not isinstance(part, str) or not part.strip() for part in value
    ):
        raise ValueError(f"{field} must be an array of non-empty strings")
    result = tuple(part.strip() for part in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must not contain duplicates")
    return result


def _positive_int(item: dict[str, Any], field: str) -> int:
    value = item.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def load_evidence_review_manifest(
    review_path: Path,
    evidence_manifest_path: Path,
    expected_event_sources: dict[str, str],
    capture_manifests: dict[str, Path],
) -> EvidenceReviewIngestion:
    """Validate operator review and bind it to verified bytes and fact excerpts.

    A review row is required for every P1 evidence record. Accepted reviews must
    confirm the source identity and original document, inventory every material
    attachment, and reproduce every linked fact's page and exact excerpt.
    This validates operator assertions; it cannot independently authenticate a
    source or prove that a human performed the described review.
    """
    verified = load_verified_evidence_manifest(
        evidence_manifest_path, expected_event_sources, capture_manifests
    )
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported review manifest schema_version")
    raw_reviews = payload.get("reviews")
    if not isinstance(raw_reviews, list):
        raise ValueError("reviews must be an array")

    evidence_by_id = {
        record.evidence_id: record
        for record in verified.bundle.evidence_records
    }
    expected_fact_rows: dict[str, set[tuple[str, int, str]]] = {}
    for link in verified.bundle.fact_links:
        expected_fact_rows.setdefault(link.evidence_id, set()).add(
            (link.fact_name, link.page_number, link.exact_excerpt)
        )

    reviews: list[DocumentReview] = []
    by_id: dict[str, DocumentReview] = {}
    for item in raw_reviews:
        if not isinstance(item, dict):
            raise ValueError("each review must be an object")
        evidence_id = _required_text(item, "evidence_id")
        record = evidence_by_id.get(evidence_id)
        if record is None:
            raise ValueError(f"review references unknown evidence_id: {evidence_id}")
        if record.source_tier != EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED:
            raise ValueError(f"operator review rows are only supported for P1: {evidence_id}")
        if evidence_id in by_id:
            raise ValueError(f"duplicate review evidence_id: {evidence_id}")

        capture = verified.verified_captures.get(evidence_id)
        if capture is None:
            raise ValueError(f"missing verified capture for review {evidence_id}")
        supplied_event_id = _required_text(item, "event_id")
        source_record_id = _required_text(item, "source_record_id")
        source_url = _required_text(item, "source_url")
        document_type = _required_text(item, "document_type")
        content_sha256 = _required_text(item, "content_sha256")
        lineage = {
            "event_id": (supplied_event_id, capture.event_id),
            "source_record_id": (source_record_id, capture.source_record_id),
            "source_url": (source_url, capture.source_url),
            "document_type": (document_type, capture.document_type),
            "content_sha256": (content_sha256, capture.sha256),
        }
        for field, (supplied, captured) in lineage.items():
            if supplied != captured:
                raise ValueError(f"review {field} mismatch for {evidence_id}")

        try:
            status = EvidenceReviewStatus(_required_text(item, "review_status"))
        except ValueError as error:
            raise ValueError(f"invalid review_status for {evidence_id}") from error

        attachment_inventory = _string_list(item, "attachment_inventory")
        reviewed_attachments = _string_list(item, "reviewed_attachments")
        expected_attachments = set(
            verified.bundle.material_attachment_names[evidence_id]
        )
        if set(attachment_inventory) != expected_attachments:
            raise ValueError(f"attachment inventory mismatch for {evidence_id}")
        if not set(reviewed_attachments).issubset(attachment_inventory):
            raise ValueError(f"reviewed attachment not in inventory for {evidence_id}")

        raw_facts = item.get("fact_reviews")
        if not isinstance(raw_facts, list):
            raise ValueError(f"fact_reviews must be an array for {evidence_id}")
        facts: list[ReviewedFact] = []
        for fact in raw_facts:
            if not isinstance(fact, dict):
                raise ValueError(f"each fact review must be an object for {evidence_id}")
            facts.append(
                ReviewedFact(
                    fact_name=_required_text(fact, "fact_name"),
                    page_number=_positive_int(fact, "page_number"),
                    exact_excerpt=_required_text(fact, "exact_excerpt"),
                )
            )
        fact_keys = [
            (fact.fact_name, fact.page_number, fact.exact_excerpt) for fact in facts
        ]
        if len(fact_keys) != len(set(fact_keys)):
            raise ValueError(f"duplicate fact review for {evidence_id}")

        page_count = _positive_int(item, "page_count")
        if any(fact.page_number > page_count for fact in facts):
            raise ValueError(f"fact page exceeds page_count for {evidence_id}")

        review = DocumentReview(
            evidence_id=evidence_id,
            event_id=record.event_id,
            source_record_id=source_record_id,
            source_url=source_url,
            document_type=document_type,
            content_sha256=content_sha256,
            reviewer_id=_required_text(item, "reviewer_id"),
            reviewer_role=_required_text(item, "reviewer_role"),
            reviewed_at=_aware_time(item.get("reviewed_at"), "reviewed_at"),
            review_status=status,
            source_identity_verified=item.get("source_identity_verified") is True,
            original_document_confirmed=item.get("original_document_confirmed") is True,
            page_count=page_count,
            attachment_inventory=attachment_inventory,
            reviewed_attachments=reviewed_attachments,
            fact_reviews=tuple(facts),
        )

        if status == EvidenceReviewStatus.ACCEPTED:
            if record.review_status != EvidenceReviewStatus.ACCEPTED:
                raise ValueError(f"provenance review_status is not accepted for {evidence_id}")
            if not review.source_identity_verified:
                raise ValueError(f"source identity is not verified for {evidence_id}")
            if not review.original_document_confirmed or not record.original_document:
                raise ValueError(f"original document is not confirmed for {evidence_id}")
            if not record.directly_reviewed:
                raise ValueError(f"provenance does not record direct review for {evidence_id}")
            if record.material_attachments_required and not attachment_inventory:
                raise ValueError(f"required attachment inventory is empty for {evidence_id}")
            if set(reviewed_attachments) != set(attachment_inventory):
                raise ValueError(f"material attachments are not fully reviewed for {evidence_id}")
            if set(fact_keys) != expected_fact_rows.get(evidence_id, set()):
                raise ValueError(
                    f"reviewed fact excerpts do not match provenance for {evidence_id}"
                )

        by_id[evidence_id] = review
        reviews.append(review)

    required_p1 = {
        record.evidence_id
        for record in verified.bundle.evidence_records
        if record.source_tier == EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED
    }
    missing = required_p1 - set(by_id)
    if missing:
        raise ValueError(
            "missing operator review rows for P1 evidence: " + ", ".join(sorted(missing))
        )

    return EvidenceReviewIngestion(
        verified_evidence=verified,
        document_reviews=tuple(reviews),
    )
