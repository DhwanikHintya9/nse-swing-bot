from datetime import UTC, datetime
from types import SimpleNamespace

from nse_swing_bot.events.evidence import (
    CanonicalEvent,
    EventDirection,
    EventTaxonomy,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceTier,
)
from nse_swing_bot.events import preflight


def _setup():
    record = EvidenceRecord(
        evidence_id="EVD-1",
        event_id="EV-1",
        source_tier=EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED,
        review_status=EvidenceReviewStatus.ACCEPTED,
        source_url="https://nsearchives.nseindia.com/filing.pdf",
        retrieved_at=datetime(2026, 11, 6, tzinfo=UTC),
        published_at=None,
        content_sha256="a" * 64,
        original_document=True,
        directly_reviewed=True,
        material_attachments_required=False,
        material_attachments_reviewed=True,
        exact_excerpt="appointed for five years",
    )
    event = CanonicalEvent(
        event_id="EV-1",
        symbol="TEST",
        source_record_id="SRC-1",
        event_class=EventTaxonomy.MANAGEMENT_GOVERNANCE,
        event_subclass="director_appointment",
        announcement_at=datetime(2026, 11, 6, tzinfo=UTC),
        direction=EventDirection.UNKNOWN,
        required_fact_evidence={"appointment_term": ("EVD-1",)},
    )
    bundle = SimpleNamespace(evidence_records=(record,))
    verified = SimpleNamespace(bundle=bundle)
    review = SimpleNamespace(
        evidence_id="EVD-1",
        review_status=EvidenceReviewStatus.ACCEPTED,
        page_count=2,
    )
    ingestion = SimpleNamespace(
        verified_evidence=verified,
        document_reviews=(review,),
        accepted_evidence_ids=("EVD-1",),
    )
    return event, ingestion


def test_preflight_requires_pdf_artifact_bundle_for_p1(tmp_path):
    event, ingestion = _setup()
    result = preflight.evaluate_preflighted_event_evidence(
        event, ingestion, {}
    )
    assert not result.eligible
    assert "missing_pdf_artifact_bundle:EVD-1" in result.reasons


def test_preflight_admits_only_after_artifact_and_review_gates(tmp_path, monkeypatch):
    event, ingestion = _setup()
    monkeypatch.setattr(
        preflight,
        "verify_pdf_artifact_bundle",
        lambda *_args: SimpleNamespace(page_count=2),
    )
    result = preflight.evaluate_preflighted_event_evidence(
        event,
        ingestion,
        {"EVD-1": (tmp_path / "inspection.json", (tmp_path / "binding.json",))},
    )
    assert result.eligible
    assert result.admitted_evidence_ids == ("EVD-1",)


def test_preflight_rejects_review_page_count_mismatch(tmp_path, monkeypatch):
    event, ingestion = _setup()
    monkeypatch.setattr(
        preflight,
        "verify_pdf_artifact_bundle",
        lambda *_args: SimpleNamespace(page_count=3),
    )
    result = preflight.evaluate_preflighted_event_evidence(
        event,
        ingestion,
        {"EVD-1": (tmp_path / "inspection.json", (tmp_path / "binding.json",))},
    )
    assert not result.eligible
    assert "review_pdf_page_count_mismatch:EVD-1" in result.reasons


def test_preflight_rejects_invalid_pdf_artifacts(tmp_path, monkeypatch):
    event, ingestion = _setup()

    def fail(*_args):
        raise ValueError("bad excerpt digest")

    monkeypatch.setattr(preflight, "verify_pdf_artifact_bundle", fail)
    result = preflight.evaluate_preflighted_event_evidence(
        event,
        ingestion,
        {"EVD-1": (tmp_path / "inspection.json", (tmp_path / "binding.json",))},
    )
    assert not result.eligible
    assert any(
        reason.startswith("invalid_pdf_artifact_bundle:EVD-1:")
        for reason in result.reasons
    )


def test_preflight_rejects_unaccepted_operator_review(tmp_path):
    event, ingestion = _setup()
    ingestion.document_reviews = (
        SimpleNamespace(
            evidence_id="EVD-1",
            review_status=EvidenceReviewStatus.PENDING,
            page_count=2,
        ),
    )
    result = preflight.evaluate_preflighted_event_evidence(
        event,
        ingestion,
        {"EVD-1": (tmp_path / "inspection.json", (tmp_path / "binding.json",))},
    )
    assert not result.eligible
    assert "operator_review_not_accepted:EVD-1" in result.reasons
