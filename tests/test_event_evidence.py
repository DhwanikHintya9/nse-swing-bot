from datetime import UTC, datetime
from pathlib import Path

import pytest

from nse_swing_bot.events.evidence import (
    CanonicalEvent,
    EventDirection,
    EventTaxonomy,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceTier,
    evaluate_event_evidence,
)
from nse_swing_bot.events.migration import (
    load_source_id_aliases,
    resolve_source_record_ids,
)

PUBLISHED = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
RETRIEVED = datetime(2026, 11, 4, 9, 5, tzinfo=UTC)
SHA = "a" * 64


def event(**overrides):
    values = {
        "event_id": "EV-ABC-01",
        "symbol": "ABC",
        "source_record_id": "triage-record-1",
        "event_class": EventTaxonomy.MANAGEMENT_GOVERNANCE,
        "event_subclass": "director_appointment",
        "announcement_at": PUBLISHED,
        "direction": EventDirection.UNKNOWN,
        "required_fact_evidence": {"appointment_term": ("evidence-1",)},
    }
    values.update(overrides)
    return CanonicalEvent(**values)


def evidence(**overrides):
    values = {
        "evidence_id": "evidence-1",
        "event_id": "EV-ABC-01",
        "source_tier": EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED,
        "review_status": EvidenceReviewStatus.ACCEPTED,
        "source_url": "https://www.nseindia.com/filing.pdf",
        "retrieved_at": RETRIEVED,
        "published_at": PUBLISHED,
        "content_sha256": SHA,
        "original_document": True,
        "directly_reviewed": True,
        "material_attachments_required": True,
        "material_attachments_reviewed": True,
        "exact_excerpt": "Appointment for a term of five years, subject to shareholder approval.",
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def test_directly_reviewed_primary_evidence_is_admitted():
    result = evaluate_event_evidence(event(), [evidence()])
    assert result.eligible
    assert result.reasons == ()
    assert result.admitted_evidence_ids == ("evidence-1",)


@pytest.mark.parametrize(
    "tier",
    [
        EvidenceTier.P2_ISSUER_SIGNED_MIRROR,
        EvidenceTier.P3_EXCHANGE_METADATA_ONLY,
        EvidenceTier.P4_SECONDARY_MEDIA,
        EvidenceTier.P5_UNKNOWN_OR_INACCESSIBLE,
    ],
)
def test_secondary_or_metadata_evidence_never_satisfies_production_fact(tier):
    result = evaluate_event_evidence(event(), [evidence(source_tier=tier)])
    assert not result.eligible
    assert "non_primary_evidence:appointment_term:evidence-1" in result.reasons
    assert result.admitted_evidence_ids == ()


def test_primary_evidence_pending_review_is_not_admitted():
    result = evaluate_event_evidence(
        event(), [evidence(review_status=EvidenceReviewStatus.PENDING)]
    )
    assert not result.eligible
    assert "primary_evidence_not_accepted:appointment_term:evidence-1" in result.reasons


def test_missing_material_annexure_rejects_p1_evidence_record():
    with pytest.raises(ValueError, match="material attachments"):
        evidence(material_attachments_reviewed=False)


def test_p1_requires_original_document_direct_review_and_hash():
    with pytest.raises(ValueError, match="original document"):
        evidence(original_document=False)
    with pytest.raises(ValueError, match="directly reviewed"):
        evidence(directly_reviewed=False)
    with pytest.raises(ValueError, match="SHA-256"):
        evidence(content_sha256=None)


def test_each_material_fact_needs_its_own_p1_evidence():
    item = event(
        required_fact_evidence={
            "appointment_term": ("evidence-1",),
            "shareholder_approval": ("evidence-2",),
        }
    )
    result = evaluate_event_evidence(item, [evidence()])
    assert not result.eligible
    assert "missing_evidence:shareholder_approval:evidence-2" in result.reasons


def test_evidence_from_another_event_is_rejected():
    result = evaluate_event_evidence(event(), [evidence(event_id="EV-OTHER")])
    assert not result.eligible
    assert "evidence_event_mismatch:evidence-1" in result.reasons


def test_naive_event_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        event(announcement_at=datetime(2026, 11, 4, 9, 0))


def test_p1_source_requires_absolute_http_url_and_sha_format():
    with pytest.raises(ValueError, match="absolute HTTP"):
        evidence(source_url="nse-filing.pdf")
    with pytest.raises(ValueError, match="64-character"):
        evidence(content_sha256="not-a-hash")


def _alias_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "data"
        / "corporate_events"
        / "source-id-aliases.csv"
    )


def test_aavas_aliases_resolve_only_exact_event_ids_and_preserve_legacy_value():
    aliases = load_source_id_aliases(_alias_path())
    legacy = "463fe7e016f91dd6bcc"
    triage = "463fe7e016f91dd6bcc8"
    event_ids = {f"EV-AAVAS-0{i}": legacy for i in range(1, 5)}
    resolved = resolve_source_record_ids(event_ids, {triage}, aliases)
    assert set(resolved) == set(event_ids)
    assert set(resolved.values()) == {triage}
    assert all(item.legacy_source_record_id == legacy for item in aliases)


def test_alias_must_match_original_legacy_id():
    aliases = load_source_id_aliases(_alias_path())
    with pytest.raises(ValueError, match="legacy ID mismatch"):
        resolve_source_record_ids(
            {"EV-AAVAS-01": "different-id"},
            {"463fe7e016f91dd6bcc8"},
            aliases[:1],
        )


def test_alias_target_must_exist_in_triage():
    aliases = load_source_id_aliases(_alias_path())
    with pytest.raises(ValueError, match="absent from triage"):
        resolve_source_record_ids(
            {"EV-AAVAS-01": "463fe7e016f91dd6bcc"},
            set(),
            aliases[:1],
        )


def test_unmatched_ids_fail_instead_of_prefix_matching():
    with pytest.raises(ValueError, match="unresolved source record ID"):
        resolve_source_record_ids(
            {"EV-OTHER": "prefix-123"},
            {"prefix-1234"},
            [],
        )


def test_alias_file_rejects_duplicate_event_ids(tmp_path):
    path = tmp_path / "aliases.csv"
    path.write_text(
        "canonical_event_id,legacy_source_record_id,resolved_source_record_id,reason\n"
        "EV-1,old,new,reviewed\nEV-1,old,new,duplicate\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate canonical_event_id"):
        load_source_id_aliases(path)
