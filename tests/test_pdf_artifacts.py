import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nse_swing_bot.events import pdf_artifacts


def _fixture(tmp_path: Path):
    digest = "a" * 64
    capture = SimpleNamespace(
        manifest_path=tmp_path / "capture.json",
        archive_path=tmp_path / "filing.pdf",
        sha256=digest,
        byte_length=123,
        event_id="EV-1",
        source_record_id="SRC-1",
        source_url="https://nsearchives.nseindia.com/filing.pdf",
        document_type="issuer_filing_pdf",
    )
    record = SimpleNamespace(
        evidence_id="EVD-1",
        event_id="EV-1",
        source_url=capture.source_url,
    )
    link = SimpleNamespace(
        evidence_id="EVD-1",
        fact_name="appointment_term",
        page_number=2,
        exact_excerpt="appointed for five years",
        attachment_name=None,
    )
    bundle = SimpleNamespace(
        evidence_records=(record,),
        source_record_ids={"EVD-1": "SRC-1"},
        document_types={"EVD-1": "issuer_filing_pdf"},
        material_attachment_names={"EVD-1": ()},
        fact_links=(link,),
    )
    ingestion = SimpleNamespace(
        bundle=bundle,
        verified_captures={"EVD-1": capture},
    )
    inspection = {
        "schema_version": 1,
        "inspection_mode": "captured_pdf_read_only_metadata_and_text_fingerprints",
        "event_id": "EV-1",
        "source_record_id": "SRC-1",
        "source_url": capture.source_url,
        "document_type": "issuer_filing_pdf",
        "pdf_sha256": digest,
        "pdf_byte_length": 123,
        "pdf_filename": "filing.pdf",
        "page_count": 2,
        "pages": [
            {"page_number": 1, "text_sha256": "b" * 64},
            {"page_number": 2, "text_sha256": "c" * 64},
        ],
    }
    inspection_path = tmp_path / "inspection.json"
    inspection_path.write_text(json.dumps(inspection))
    excerpt = {
        "event_id": "EV-1",
        "source_record_id": "SRC-1",
        "source_url": capture.source_url,
        "document_type": "issuer_filing_pdf",
        "pdf_sha256": digest,
        "page_number": 2,
        "page_text_sha256": "c" * 64,
        "exact_excerpt": "appointed for five years",
        "excerpt_sha256": "d" * 64,
        "evidence_review_status": "pending",
    }
    excerpt_path = tmp_path / "excerpt.json"
    excerpt_path.write_text(json.dumps(excerpt))
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps({
        "schema_version": 1,
        "evidence_id": "EVD-1",
        "fact_name": "appointment_term",
        "attachment_name": None,
        "inspection_manifest": "inspection.json",
        "excerpt_manifest": "excerpt.json",
    }))
    return ingestion, inspection_path, binding_path, excerpt


def test_pdf_artifacts_bind_exact_excerpt_to_provenance_and_inspection(tmp_path, monkeypatch):
    ingestion, inspection, binding, excerpt = _fixture(tmp_path)
    monkeypatch.setattr(
        pdf_artifacts,
        "verify_exact_pdf_excerpt",
        lambda *_args: excerpt,
    )
    result = pdf_artifacts.verify_pdf_artifact_bundle(
        ingestion, "EVD-1", inspection, (binding,)
    )
    assert result.evidence_id == "EVD-1"
    assert result.page_count == 2
    assert result.verified_excerpt_count == 1


def test_pdf_artifact_bundle_rejects_missing_fact_binding(tmp_path, monkeypatch):
    ingestion, inspection, binding, _ = _fixture(tmp_path)
    monkeypatch.setattr(
        pdf_artifacts,
        "verify_exact_pdf_excerpt",
        lambda *_args: {},
    )
    with pytest.raises(ValueError, match="missing PDF excerpt bindings"):
        pdf_artifacts.verify_pdf_artifact_bundle(
            ingestion, "EVD-1", inspection, ()
        )


def test_pdf_artifact_bundle_rejects_inspection_digest_mismatch(tmp_path):
    ingestion, inspection, binding, _ = _fixture(tmp_path)
    payload = json.loads(inspection.read_text())
    payload["pdf_sha256"] = "f" * 64
    inspection.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="pdf_sha256 mismatch"):
        pdf_artifacts.verify_pdf_artifact_bundle(
            ingestion, "EVD-1", inspection, (binding,)
        )


def test_pdf_artifact_bundle_rejects_excerpt_page_text_mismatch(tmp_path, monkeypatch):
    ingestion, inspection, binding, excerpt = _fixture(tmp_path)
    bad = dict(excerpt, page_text_sha256="e" * 64)
    monkeypatch.setattr(
        pdf_artifacts,
        "verify_exact_pdf_excerpt",
        lambda *_args: excerpt,
    )
    (tmp_path / "excerpt.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="excerpt page_text_sha256 mismatch"):
        pdf_artifacts.verify_pdf_artifact_bundle(
            ingestion, "EVD-1", inspection, (binding,)
        )
