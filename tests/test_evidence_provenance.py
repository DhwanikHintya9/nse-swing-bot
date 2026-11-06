import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nse_swing_bot.events.evidence import EvidenceTier
from nse_swing_bot.events.provenance import load_evidence_manifest

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC).isoformat()


def _document(evidence_id="ev-1", event_id="DABUR-CEO", source_id="src-1", **overrides):
    item = {
        "evidence_id": evidence_id,
        "event_id": event_id,
        "source_record_id": source_id,
        "document_type": "exchange_filing_pdf",
        "source_tier": EvidenceTier.P1_DIRECT_PRIMARY_REVIEWED.value,
        "review_status": "accepted",
        "source_url": "https://nse.example/filing.pdf",
        "retrieved_at": NOW,
        "published_at": NOW,
        "content_sha256": "a" * 64,
        "original_document": True,
        "directly_reviewed": True,
        "material_attachments_required": True,
        "material_attachments_reviewed": True,
        "material_attachment_names": ["annexure-a.pdf"],
        "reviewed_material_attachment_names": ["annexure-a.pdf"],
        "document_excerpt": "The board approved the appointment.",
    }
    item.update(overrides)
    return item


def _link(event_id="DABUR-CEO", evidence_id="ev-1", fact="appointment", **overrides):
    item = {
        "event_id": event_id,
        "evidence_id": evidence_id,
        "fact_name": fact,
        "page_number": 2,
        "exact_excerpt": "The board approved the appointment.",
    }
    item.update(overrides)
    return item


def _load(tmp_path: Path, documents, links, expected=None):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "schema_version": 1, "documents": documents, "fact_links": links
    }), encoding="utf-8")
    return load_evidence_manifest(path, expected or {"DABUR-CEO": "src-1"})


def test_manifest_builds_event_fact_evidence_map(tmp_path):
    bundle = _load(
        tmp_path,
        [_document()],
        [_link(), _link(fact="shareholder_approval")],
    )
    assert bundle.required_fact_evidence == {
        "DABUR-CEO": {
            "appointment": ("ev-1",),
            "shareholder_approval": ("ev-1",),
        }
    }
    assert bundle.fact_links[0].page_number == 2
    assert bundle.fact_links[0].exact_excerpt


def test_mixed_dabur_events_keep_evidence_separate(tmp_path):
    documents = [
        _document(),
        _document(
            evidence_id="ev-auditor",
            event_id="DABUR-AUDITOR",
            source_id="src-2",
            source_tier="P4_SECONDARY_MEDIA",
            review_status="pending",
            original_document=False,
            directly_reviewed=False,
            material_attachments_required=False,
            material_attachments_reviewed=False,
        ),
    ]
    links = [
        _link(),
        _link(event_id="DABUR-AUDITOR", evidence_id="ev-auditor", fact="auditor_appointment"),
    ]
    bundle = _load(
        tmp_path, documents, links,
        {"DABUR-CEO": "src-1", "DABUR-AUDITOR": "src-2"},
    )
    assert bundle.required_fact_evidence["DABUR-CEO"]["appointment"] == ("ev-1",)
    assert bundle.required_fact_evidence["DABUR-AUDITOR"]["auditor_appointment"] == (
        "ev-auditor",
    )
    assert bundle.evidence_records[1].source_tier == EvidenceTier.P4_SECONDARY_MEDIA


def test_primary_document_without_hash_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="SHA-256"):
        _load(tmp_path, [_document(content_sha256=None)], [_link()])


def test_primary_document_with_unreviewed_material_attachment_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="material attachments"):
        _load(tmp_path, [_document(material_attachments_reviewed=False)], [_link()])


def test_source_record_mismatch_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="source record mismatch"):
        _load(tmp_path, [_document(source_record_id="wrong")], [_link()])


def test_fact_link_requires_page_and_exact_excerpt(tmp_path):
    with pytest.raises(ValueError, match="page_number"):
        _load(tmp_path, [_document()], [_link(page_number=0)])
    with pytest.raises(ValueError, match="exact_excerpt"):
        _load(tmp_path, [_document()], [_link(exact_excerpt=" ")])


def test_fact_link_cannot_cross_event_boundary(tmp_path):
    with pytest.raises(ValueError, match="event mismatch"):
        _load(
            tmp_path,
            [_document()],
            [_link(event_id="DABUR-AUDITOR")],
            {"DABUR-CEO": "src-1", "DABUR-AUDITOR": "src-2"},
        )


def test_missing_document_reference_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown evidence_id"):
        _load(tmp_path, [_document()], [_link(evidence_id="missing")])


def _capture_for_document(tmp_path: Path, document):
    from nse_swing_bot.events.capture import capture_source_bytes

    source = tmp_path / "issuer-filing.pdf"
    source.write_bytes(b"%PDF-1.7\\nissuer filing bytes\\n")
    captured = capture_source_bytes(
        source,
        tmp_path / "archive",
        event_id=document["event_id"],
        source_record_id=document["source_record_id"],
        source_url=document["source_url"],
        document_type=document["document_type"],
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    return captured


def test_verified_manifest_binds_p1_to_exact_capture_lineage(tmp_path):
    from nse_swing_bot.events.provenance import load_verified_evidence_manifest

    document = _document()
    captured = _capture_for_document(tmp_path, document)
    document["content_sha256"] = captured.sha256
    bundle_path = tmp_path / "manifest.json"
    bundle_path.write_text(json.dumps({
        "schema_version": 1,
        "documents": [document],
        "fact_links": [_link()],
    }), encoding="utf-8")

    result = load_verified_evidence_manifest(
        bundle_path,
        {"DABUR-CEO": "src-1"},
        {"ev-1": captured.manifest_path},
    )

    assert result.verified_captures["ev-1"].sha256 == captured.sha256
    assert result.bundle.evidence_records[0].review_status.value == "accepted"


def test_verified_manifest_rejects_missing_p1_capture(tmp_path):
    from nse_swing_bot.events.provenance import load_verified_evidence_manifest

    _load(tmp_path, [_document()], [_link()])
    path = tmp_path / "manifest.json"
    with pytest.raises(ValueError, match="missing verified capture"):
        load_verified_evidence_manifest(path, {"DABUR-CEO": "src-1"}, {})


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("event_id", "OTHER-EVENT"),
        ("source_record_id", "wrong-source"),
        ("source_url", "https://wrong.example/filing.pdf"),
        ("document_type", "issuer_signed_mirror"),
    ],
)
def test_verified_manifest_rejects_capture_lineage_mismatch(tmp_path, field, wrong_value):
    from nse_swing_bot.events.capture import capture_source_bytes
    from nse_swing_bot.events.provenance import load_verified_evidence_manifest

    document = _document()
    source = tmp_path / "issuer-filing.pdf"
    source.write_bytes(b"%PDF-1.7\\nissuer filing bytes\\n")
    metadata = {
        "event_id": document["event_id"],
        "source_record_id": document["source_record_id"],
        "source_url": document["source_url"],
        "document_type": document["document_type"],
    }
    metadata[field] = wrong_value
    captured = capture_source_bytes(
        source,
        tmp_path / "archive",
        **metadata,
        captured_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )
    document["content_sha256"] = captured.sha256
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "schema_version": 1, "documents": [document], "fact_links": [_link()]
    }), encoding="utf-8")

    with pytest.raises(ValueError, match=f"capture {field} mismatch"):
        load_verified_evidence_manifest(
            path, {"DABUR-CEO": "src-1"}, {"ev-1": captured.manifest_path}
        )


def test_verified_manifest_rejects_capture_hash_mismatch(tmp_path):
    from nse_swing_bot.events.provenance import load_verified_evidence_manifest

    document = _document()
    captured = _capture_for_document(tmp_path, document)
    document["content_sha256"] = "b" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "schema_version": 1, "documents": [document], "fact_links": [_link()]
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="capture sha256 mismatch"):
        load_verified_evidence_manifest(
            path, {"DABUR-CEO": "src-1"}, {"ev-1": captured.manifest_path}
        )


def test_verified_manifest_rejects_unknown_capture_evidence_id(tmp_path):
    from nse_swing_bot.events.provenance import load_verified_evidence_manifest

    _load(tmp_path, [_document()], [_link()])
    path = tmp_path / "manifest.json"
    with pytest.raises(ValueError, match="unknown evidence IDs"):
        load_verified_evidence_manifest(
            path, {"DABUR-CEO": "src-1"}, {"not-an-evidence-id": tmp_path / "missing.json"}
        )



def test_fact_link_can_name_a_declared_material_attachment(tmp_path):
    bundle = _load(
        tmp_path,
        [_document()],
        [_link(attachment_name="annexure-a.pdf")],
    )
    assert bundle.fact_links[0].attachment_name == "annexure-a.pdf"


def test_fact_link_cannot_name_an_unknown_attachment(tmp_path):
    with pytest.raises(ValueError, match="unknown fact attachment"):
        _load(
            tmp_path,
            [_document()],
            [_link(attachment_name="annexure-b.pdf")],
        )
