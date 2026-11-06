"""End-to-end preflight for reviewed event evidence and PDF artifacts."""
from __future__ import annotations

from pathlib import Path

from nse_swing_bot.events.evidence import (
    CanonicalEvent,
    EvidenceAdmissionResult,
)
from nse_swing_bot.events.pdf_artifacts import verify_pdf_artifact_bundle
from nse_swing_bot.events.review import (
    EvidenceReviewIngestion,
    evaluate_reviewed_event_evidence,
)


def evaluate_preflighted_event_evidence(
    event: CanonicalEvent,
    ingestion: EvidenceReviewIngestion,
    pdf_artifacts: dict[str, tuple[Path, tuple[Path, ...]]],
) -> EvidenceAdmissionResult:
    """Require verified PDF artifacts for every P1 fact source before admission.

    pdf_artifacts maps evidence_id to (inspection_manifest_path,
    excerpt_binding_paths). Every P1 evidence ID referenced by the event's
    required facts must have a complete verified PDF artifact bundle. This
    function then delegates to the existing accepted-operator-review gate.
    Missing or invalid artifacts fail closed and never mutate review state.
    """
    evidence_by_id = {
        record.evidence_id: record
        for record in ingestion.verified_evidence.bundle.evidence_records
    }
    review_by_id = {
        review.evidence_id: review
        for review in ingestion.document_reviews
    }
    required_ids = {
        evidence_id
        for evidence_ids in event.required_fact_evidence.values()
        for evidence_id in evidence_ids
    }
    reasons: list[str] = []
    for evidence_id in sorted(required_ids):
        record = evidence_by_id.get(evidence_id)
        if record is None:
            reasons.append(f"missing_evidence:{evidence_id}")
            continue
        if record.source_tier.value != "P1_DIRECT_PRIMARY_REVIEWED":
            continue
        review = review_by_id.get(evidence_id)
        if review is None or review.evidence_id not in ingestion.accepted_evidence_ids:
            reasons.append(f"operator_review_not_accepted:{evidence_id}")
            continue
        artifact_paths = pdf_artifacts.get(evidence_id)
        if artifact_paths is None:
            reasons.append(f"missing_pdf_artifact_bundle:{evidence_id}")
            continue
        inspection_path, binding_paths = artifact_paths
        try:
            artifact = verify_pdf_artifact_bundle(
                ingestion.verified_evidence,
                evidence_id,
                inspection_path,
                binding_paths,
            )
        except (OSError, ValueError) as error:
            reasons.append(f"invalid_pdf_artifact_bundle:{evidence_id}:{error}")
            continue
        if artifact.page_count != review.page_count:
            reasons.append(f"review_pdf_page_count_mismatch:{evidence_id}")
    if reasons:
        return EvidenceAdmissionResult(
            eligible=False,
            reasons=tuple(reasons),
            admitted_evidence_ids=(),
        )
    return evaluate_reviewed_event_evidence(event, ingestion)
