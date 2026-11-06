"""Versioned event facts and fail-closed evidence admission.

The legacy market_data.event_calendar model remains untouched. These contracts
make direct review of original exchange/issuer documents explicit before any
event can be admitted to a production policy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse


class EvidenceTier(StrEnum):
    P1_DIRECT_PRIMARY_REVIEWED = "P1_DIRECT_PRIMARY_REVIEWED"
    P2_ISSUER_SIGNED_MIRROR = "P2_ISSUER_SIGNED_MIRROR"
    P3_EXCHANGE_METADATA_ONLY = "P3_EXCHANGE_METADATA_ONLY"
    P4_SECONDARY_MEDIA = "P4_SECONDARY_MEDIA"
    P5_UNKNOWN_OR_INACCESSIBLE = "P5_UNKNOWN_OR_INACCESSIBLE"


class EvidenceReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


class EventDirection(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class EventTaxonomy(StrEnum):
    MANAGEMENT_GOVERNANCE = "management_governance"
    FINANCIAL_RESULTS = "financial_results"
    DIVIDEND_CAPITAL_ALLOCATION = "dividend_capital_allocation"
    FUNDRAISING_DEBT = "fundraising_debt"
    ACQUISITION_DISPOSAL_JV = "acquisition_disposal_jv"
    ORDERS_CONTRACTS = "orders_contracts"
    REGULATORY_LEGAL = "regulatory_legal"
    CREDIT_RATING = "credit_rating"
    OPERATIONS = "operations"
    SHARE_CAPITAL_ESOP = "share_capital_esop"
    RELATED_PARTY = "related_party"
    DISCLOSURE_PROCESS = "disclosure_process"


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _require_http_url(value: str, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field} must be an absolute HTTP(S) URL")


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    event_id: str
    source_tier: EvidenceTier
    review_status: EvidenceReviewStatus
    source_url: str
    retrieved_at: datetime
    published_at: datetime | None
    content_sha256: str | None
    original_document: bool
    directly_reviewed: bool
    material_attachments_required: bool
    material_attachments_reviewed: bool
    exact_excerpt: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.event_id.strip():
            raise ValueError("evidence_id and event_id are required")
        _require_http_url(self.source_url, "source_url")
        _require_aware(self.retrieved_at, "retrieved_at")
        if self.published_at is not None:
            _require_aware(self.published_at, "published_at")
        if self.content_sha256 is not None and not re.fullmatch(
            r"[0-9a-fA-F]{64}", self.content_sha256
        ):
            raise ValueError("content_sha256 must be a 64-character hexadecimal SHA-256")
        if self.source_tier == EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED:
            if not self.original_document:
                raise ValueError("P1 evidence must be the original document")
            if not self.directly_reviewed:
                raise ValueError("P1 evidence must be directly reviewed")
            if not self.content_sha256:
                raise ValueError("P1 evidence must have a captured content SHA-256")
            if self.material_attachments_required and not self.material_attachments_reviewed:
                raise ValueError("P1 evidence must include review of material attachments")


@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    symbol: str
    source_record_id: str
    event_class: EventTaxonomy
    event_subclass: str
    announcement_at: datetime
    direction: EventDirection
    required_fact_evidence: dict[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.symbol.strip():
            raise ValueError("event_id and symbol are required")
        if not self.source_record_id.strip():
            raise ValueError("source_record_id is required")
        if not self.event_subclass.strip():
            raise ValueError("event_subclass is required")
        _require_aware(self.announcement_at, "announcement_at")
        if not self.required_fact_evidence:
            raise ValueError("at least one fact-to-evidence mapping is required")
        for fact_name, evidence_ids in self.required_fact_evidence.items():
            if not fact_name.strip() or not evidence_ids:
                raise ValueError("each required fact must reference at least one evidence ID")


@dataclass(frozen=True)
class EvidenceAdmissionResult:
    eligible: bool
    reasons: tuple[str, ...]
    admitted_evidence_ids: tuple[str, ...]


def evaluate_event_evidence(
    event: CanonicalEvent,
    evidence_records: list[EvidenceRecord],
) -> EvidenceAdmissionResult:
    """Require P1 direct-primary evidence for every fact used by a policy.

    Secondary/mirror/metadata evidence may remain attached for research and
    lineage, but cannot satisfy a production fact requirement.
    """
    by_id: dict[str, EvidenceRecord] = {}
    reasons: list[str] = []
    for record in evidence_records:
        if record.evidence_id in by_id:
            reasons.append(f"duplicate_evidence_id:{record.evidence_id}")
        by_id[record.evidence_id] = record
        if record.event_id != event.event_id:
            reasons.append(f"evidence_event_mismatch:{record.evidence_id}")

    admitted: set[str] = set()
    for fact_name, evidence_ids in event.required_fact_evidence.items():
        eligible_for_fact: list[str] = []
        for evidence_id in evidence_ids:
            record = by_id.get(evidence_id)
            if record is None:
                reasons.append(f"missing_evidence:{fact_name}:{evidence_id}")
                continue
            if record.source_tier != EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED:
                reasons.append(f"non_primary_evidence:{fact_name}:{evidence_id}")
                continue
            if record.review_status != EvidenceReviewStatus.ACCEPTED:
                reasons.append(f"primary_evidence_not_accepted:{fact_name}:{evidence_id}")
                continue
            if not record.exact_excerpt.strip():
                reasons.append(f"missing_exact_excerpt:{fact_name}:{evidence_id}")
                continue
            eligible_for_fact.append(evidence_id)
        if not eligible_for_fact:
            reasons.append(f"fact_not_supported_by_eligible_primary_evidence:{fact_name}")
        admitted.update(eligible_for_fact)

    unique_reasons = tuple(dict.fromkeys(reasons))
    return EvidenceAdmissionResult(
        eligible=not unique_reasons,
        reasons=unique_reasons,
        admitted_evidence_ids=tuple(sorted(admitted)) if not unique_reasons else (),
    )
