import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nse_swing_bot.events.capture import capture_source_bytes
from nse_swing_bot.events.evidence import (
    CanonicalEvent,
    EventDirection,
    EventTaxonomy,
    EvidenceTier,
)
from nse_swing_bot.events.review import (
    evaluate_reviewed_event_evidence,
    load_evidence_review_manifest,
)

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC).isoformat()


def _source_and_capture(tmp_path: Path):
    source = tmp_path / "issuer-filing.pdf"
    source.write_bytes(b"%PDF-1.7\\nissuer filing bytes\\n")
    return capture_source_bytes(
        source,
        tmp_path / "archive",
        event_id="EV-001",
        source_record_id="src-001",
        source_url="https://nse.example/filing.pdf",
        document_type="exchange_filing_pdf",
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )


def _manifests(tmp_path: Path, **review_overrides):
    captured = _source_and_capture(tmp_path)
    excerpt = "The board approved the appointment."
    document = {
        "evidence_id": "evidence-001",
        "event_id": "EV-001",
        "source_record_id": "src-001",
        "document_type": "exchange_filing_pdf",
        "source_tier": EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED.value,
        "review_status": "accepted",
        "source_url": "https://nse.example/filing.pdf",
        "retrieved_at": NOW,
        "published_at": NOW,
        "content_sha256": captured.sha256,
        "original_document": True,
        "directly_reviewed": True,
        "material_attachments_required": True,
        "material_attachments_reviewed": True,
        "material_attachment_names": ["annexure-a.pdf"],
        "reviewed_material_attachment_names": ["annexure-a.pdf"],
        "document_excerpt": excerpt,
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps({
        "schema_version": 1,
        "documents": [document],
        "fact_links": [{
            "event_id": "EV-001",
            "fact_name": "appointment_term",
            "evidence_id": "evidence-001",
            "page_number": 2,
            "exact_excerpt": excerpt,
        }],
    }), encoding="utf-8")
    review = {
        "evidence_id": "evidence-001",
        "event_id": "EV-001",
        "source_record_id": "src-001",
        "source_url": "https://nse.example/filing.pdf",
        "document_type": "exchange_filing_pdf",
        "content_sha256": captured.sha256,
        "reviewer_id": "reviewer-01",
        "reviewer_role": "corporate-actions-analyst",
        "reviewed_at": NOW,
        "review_status": "accepted",
        "source_identity_verified": True,
        "original_document_confirmed": True,
        "page_count": 3,
        "attachment_inventory": ["annexure-a.pdf"],
        "reviewed_attachments": ["annexure-a.pdf"],
        "attachment_page_counts": {},
        "fact_reviews": [{
            "fact_name": "appointment_term",
            "page_number": 2,
            "exact_excerpt": excerpt,
        }],
    }
    review.update(review_overrides)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps({
        "schema_version": 1, "reviews": [review]
    }), encoding="utf-8")
    args = (
        review_path,
        evidence_path,
        {"EV-001": "src-001"},
        {"evidence-001": captured.manifest_path},
    )
    return args


def test_accepted_review_binds_source_and_fact_to_verified_capture(tmp_path):
    result = load_evidence_review_manifest(*_manifests(tmp_path))
    assert result.accepted_evidence_ids == ("evidence-001",)
    review = result.document_reviews[0]
    assert review.page_count == 3
    assert review.reviewed_attachments == ("annexure-a.pdf",)
    assert review.fact_reviews[0].page_number == 2


def test_missing_p1_review_is_rejected(tmp_path):
    args = _manifests(tmp_path)
    args[0].write_text(json.dumps({"schema_version": 1, "reviews": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing operator review rows"):
        load_evidence_review_manifest(*args)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", "OTHER-EVENT"),
        ("source_record_id", "wrong-source"),
        ("source_url", "https://wrong.example/filing.pdf"),
        ("document_type", "issuer_signed_mirror"),
        ("content_sha256", "f" * 64),
    ],
)
def test_review_rejects_capture_lineage_mismatch(tmp_path, field, value):
    args = _manifests(tmp_path, **{field: value})
    with pytest.raises(ValueError, match=f"review {field} mismatch"):
        load_evidence_review_manifest(*args)


def test_accepted_review_requires_verified_source_identity(tmp_path):
    args = _manifests(tmp_path, source_identity_verified=False)
    with pytest.raises(ValueError, match="source identity is not verified"):
        load_evidence_review_manifest(*args)


def test_accepted_review_requires_original_document_confirmation(tmp_path):
    args = _manifests(tmp_path, original_document_confirmed=False)
    with pytest.raises(ValueError, match="original document is not confirmed"):
        load_evidence_review_manifest(*args)


def test_accepted_review_requires_complete_attachment_inventory(tmp_path):
    args = _manifests(tmp_path, reviewed_attachments=[])
    with pytest.raises(ValueError, match="not fully reviewed"):
        load_evidence_review_manifest(*args)


def test_review_attachment_inventory_must_match_provenance(tmp_path):
    args = _manifests(tmp_path, attachment_inventory=["different.pdf"])
    with pytest.raises(ValueError, match="attachment inventory mismatch"):
        load_evidence_review_manifest(*args)


def test_accepted_review_requires_exact_fact_page_and_excerpt(tmp_path):
    args = _manifests(tmp_path, fact_reviews=[{
        "fact_name": "appointment_term",
        "page_number": 2,
        "exact_excerpt": "A paraphrase, not the exact clause.",
    }])
    with pytest.raises(ValueError, match="reviewed fact excerpts do not match"):
        load_evidence_review_manifest(*args)


def test_review_fact_page_cannot_exceed_document_page_count(tmp_path):
    args = _manifests(tmp_path, page_count=1)
    with pytest.raises(ValueError, match="fact page exceeds page_count"):
        load_evidence_review_manifest(*args)


def test_accepted_review_requires_provenance_review_status_accepted(tmp_path):
    args = _manifests(tmp_path)
    evidence_path = args[1]
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["documents"][0]["review_status"] = "pending"
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance review_status is not accepted"):
        load_evidence_review_manifest(*args)


def test_pending_review_is_retained_but_not_accepted(tmp_path):
    args = _manifests(
        tmp_path,
        review_status="pending",
        source_identity_verified=False,
        original_document_confirmed=False,
        reviewed_attachments=[],
        fact_reviews=[],
    )
    result = load_evidence_review_manifest(*args)
    assert result.accepted_evidence_ids == ()
    assert result.document_reviews[0].review_status.value == "pending"


def test_review_rows_reject_unknown_and_duplicate_evidence_ids(tmp_path):
    args = _manifests(tmp_path)
    payload = json.loads(args[0].read_text(encoding="utf-8"))
    payload["reviews"].append(dict(payload["reviews"][0], evidence_id="unknown"))
    args[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown evidence_id"):
        load_evidence_review_manifest(*args)

    second_dir = tmp_path / "second"
    second_dir.mkdir()
    args = _manifests(second_dir)
    payload = json.loads(args[0].read_text(encoding="utf-8"))
    payload["reviews"].append(dict(payload["reviews"][0]))
    args[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate review evidence_id"):
        load_evidence_review_manifest(*args)



def _canonical_event():
    return CanonicalEvent(
        event_id="EV-001",
        symbol="DABUR",
        source_record_id="src-001",
        event_class=EventTaxonomy.MANAGEMENT_GOVERNANCE,
        event_subclass="director_appointment",
        announcement_at=datetime(2026, 11, 6, 9, 0, tzinfo=UTC),
        direction=EventDirection.NEUTRAL,
        required_fact_evidence={"appointment_term": ("evidence-001",)},
    )


def test_pending_operator_review_cannot_satisfy_event_admission(tmp_path):
    result = load_evidence_review_manifest(
        *_manifests(
            tmp_path,
            review_status="pending",
            source_identity_verified=False,
            original_document_confirmed=False,
            reviewed_attachments=[],
            fact_reviews=[],
        )
    )
    admission = evaluate_reviewed_event_evidence(_canonical_event(), result)
    assert admission.eligible is False
    assert "missing_evidence:appointment_term:evidence-001" in admission.reasons


def test_accepted_operator_review_can_reach_existing_evidence_policy(tmp_path):
    result = load_evidence_review_manifest(*_manifests(tmp_path))
    admission = evaluate_reviewed_event_evidence(_canonical_event(), result)
    assert admission.eligible is True
    assert admission.admitted_evidence_ids == ("evidence-001",)



def _scope_fact_to_attachment(args, *, attachment_pages=4, include_page_count=True):
    review_path, evidence_path, expected, captures = args
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["fact_links"][0]["attachment_name"] = "annexure-a.pdf"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review_row = review["reviews"][0]
    review_row["fact_reviews"][0]["attachment_name"] = "annexure-a.pdf"
    if include_page_count:
        review_row["attachment_page_counts"] = {"annexure-a.pdf": attachment_pages}
    review_path.write_text(json.dumps(review), encoding="utf-8")
    return args


def test_accepted_review_supports_fact_excerpt_from_named_annexure(tmp_path):
    args = _scope_fact_to_attachment(_manifests(tmp_path))
    result = load_evidence_review_manifest(*args)
    assert result.accepted_evidence_ids == ("evidence-001",)
    assert result.document_reviews[0].fact_reviews[0].attachment_name == "annexure-a.pdf"


def test_attachment_fact_requires_its_own_page_count(tmp_path):
    args = _scope_fact_to_attachment(
        _manifests(tmp_path), include_page_count=False
    )
    with pytest.raises(ValueError, match="missing attachment page count"):
        load_evidence_review_manifest(*args)


def test_attachment_fact_page_must_be_within_attachment_page_count(tmp_path):
    args = _scope_fact_to_attachment(_manifests(tmp_path), attachment_pages=1)
    with pytest.raises(ValueError, match="fact page exceeds attachment page count"):
        load_evidence_review_manifest(*args)


def test_review_fact_cannot_reference_an_uninventoried_attachment(tmp_path):
    args = _manifests(tmp_path)
    review_path = args[0]
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["reviews"][0]["fact_reviews"][0]["attachment_name"] = "annexure-b.pdf"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="fact references unknown attachment"):
        load_evidence_review_manifest(*args)
