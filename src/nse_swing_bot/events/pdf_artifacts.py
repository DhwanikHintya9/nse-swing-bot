"""Cross-check PDF inspection and exact-excerpt artifacts against evidence provenance."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nse_swing_bot.events.pdf_inspection import verify_exact_pdf_excerpt
from nse_swing_bot.events.provenance import VerifiedEvidenceIngestion


@dataclass(frozen=True)
class VerifiedPdfArtifactBundle:
    """PDF artifacts bound to one provenance evidence record."""

    evidence_id: str
    event_id: str
    source_record_id: str
    pdf_sha256: str
    page_count: int
    verified_excerpt_count: int
    attachment_names: tuple[str, ...]


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {label}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def verify_pdf_artifact_bundle(
    ingestion: VerifiedEvidenceIngestion,
    evidence_id: str,
    inspection_manifest_path: Path,
    excerpt_binding_paths: tuple[Path, ...],
) -> VerifiedPdfArtifactBundle:
    """Verify PDF inspection and fact-excerpt bindings for one evidence record.

    Each binding is an operator-authored JSON object with schema_version=1,
    evidence_id, attachment_name (null for the main filing), inspection_manifest,
    and excerpt_manifest. Paths are interpreted relative to the binding file.
    Exact excerpts are rechecked against captured PDF bytes; supplied hashes and
    page numbers are not trusted. This function does not accept evidence.
    """
    records = {record.evidence_id: record for record in ingestion.bundle.evidence_records}
    record = records.get(evidence_id)
    if record is None:
        raise ValueError(f"unknown evidence_id: {evidence_id}")
    capture = ingestion.verified_captures.get(evidence_id)
    if capture is None:
        raise ValueError(f"missing verified capture for evidence {evidence_id}")
    inspection = _read_object(inspection_manifest_path, "PDF inspection manifest")
    if inspection.get("schema_version") != 1 or inspection.get("inspection_mode") != (
        "captured_pdf_read_only_metadata_and_text_fingerprints"
    ):
        raise ValueError("unsupported PDF inspection manifest")
    expected_lineage = {
        "event_id": record.event_id,
        "source_record_id": ingestion.bundle.source_record_ids[evidence_id],
        "source_url": record.source_url,
        "document_type": ingestion.bundle.document_types[evidence_id],
        "pdf_sha256": capture.sha256,
        "pdf_byte_length": capture.byte_length,
        "pdf_filename": capture.archive_path.name,
    }
    for field, expected in expected_lineage.items():
        if inspection.get(field) != expected:
            raise ValueError(f"PDF inspection {field} mismatch for {evidence_id}")
    page_count = inspection.get("page_count")
    pages = inspection.get("pages")
    if (
        not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1
        or not isinstance(pages, list) or len(pages) != page_count
    ):
        raise ValueError(f"invalid inspected page inventory for {evidence_id}")
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page.get("page_number") != index:
            raise ValueError(f"invalid inspected page sequence for {evidence_id}")
        if not isinstance(page.get("text_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", page["text_sha256"]
        ):
            raise ValueError(f"invalid inspected page text digest for {evidence_id}")

    known_facts = {
        (link.fact_name, link.page_number, link.exact_excerpt, link.attachment_name)
        for link in ingestion.bundle.fact_links if link.evidence_id == evidence_id
    }
    seen_facts: set[tuple[str, int, str, str | None]] = set()
    attachment_names: set[str] = set()
    for binding_path in excerpt_binding_paths:
        binding = _read_object(binding_path, "PDF excerpt binding")
        if binding.get("schema_version") != 1 or binding.get("evidence_id") != evidence_id:
            raise ValueError(f"excerpt binding evidence mismatch for {evidence_id}")
        attachment_name = binding.get("attachment_name")
        if attachment_name is not None and (
            not isinstance(attachment_name, str) or not attachment_name.strip()
        ):
            raise ValueError("attachment_name must be null or a non-empty string")
        if attachment_name is not None:
            attachment_name = attachment_name.strip()
            if attachment_name not in ingestion.bundle.material_attachment_names[evidence_id]:
                raise ValueError(f"unknown attachment in excerpt binding: {attachment_name}")
            attachment_names.add(attachment_name)
        inspection_path = (
            binding_path.parent / str(binding.get("inspection_manifest", ""))
        ).resolve()
        excerpt_path = (
            binding_path.parent / str(binding.get("excerpt_manifest", ""))
        ).resolve()
        if inspection_path != inspection_manifest_path.resolve():
            raise ValueError("excerpt binding points to a different inspection manifest")
        excerpt = _read_object(excerpt_path, "PDF excerpt verification manifest")
        page = excerpt.get("page_number")
        exact = excerpt.get("exact_excerpt")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1 or page > page_count:
            raise ValueError("excerpt page is outside inspected PDF page count")
        if not isinstance(exact, str) or not exact:
            raise ValueError("excerpt exact_excerpt is required")
        if excerpt.get("evidence_review_status") != "pending":
            raise ValueError("excerpt verification must remain pending")
        verified = verify_exact_pdf_excerpt(
            capture.manifest_path, page, exact
        )
        for field in (
            "event_id", "source_record_id", "source_url", "document_type",
            "pdf_sha256", "page_number", "page_text_sha256", "excerpt_sha256",
        ):
            if excerpt.get(field) != verified[field]:
                raise ValueError(f"excerpt {field} mismatch for {evidence_id}")
        page_row = pages[page - 1]
        if page_row["text_sha256"] != verified["page_text_sha256"]:
            raise ValueError(f"excerpt page text digest differs from inspection for {evidence_id}")
        expected_fact = (binding.get("fact_name"), page, exact, attachment_name)
        if expected_fact not in known_facts:
            raise ValueError(
                f"excerpt binding does not match a provenance fact link: {expected_fact}"
            )
        if expected_fact in seen_facts:
            raise ValueError(f"duplicate excerpt binding: {expected_fact}")
        seen_facts.add(expected_fact)

    if seen_facts != known_facts:
        missing = known_facts - seen_facts
        raise ValueError(f"missing PDF excerpt bindings for provenance facts: {sorted(missing)}")
    return VerifiedPdfArtifactBundle(
        evidence_id=evidence_id,
        event_id=record.event_id,
        source_record_id=ingestion.bundle.source_record_ids[evidence_id],
        pdf_sha256=capture.sha256,
        page_count=page_count,
        verified_excerpt_count=len(seen_facts),
        attachment_names=tuple(sorted(attachment_names)),
    )
