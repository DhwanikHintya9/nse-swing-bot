# Stage 4B-7 — Capture-bound operator review

The nse_swing_bot.events.review module validates a separate operator review manifest against (1) the event provenance manifest and (2) the locally archived bytes verified by the Stage 4B-5/4B-6 capture verifier.

This is a review contract, not an automated source-authenticity check. The loader validates the operator's recorded assertions and exact lineage; it cannot prove who performed the review or independently establish that a filing is genuine.

## Review manifest contract

Schema version is 1. The root object contains a reviews array. There must be exactly one review row for every P1 evidence document and no duplicate or unknown evidence IDs.

Each review row contains:

- evidence_id, event_id, source_record_id, source_url, document_type, and content_sha256, which must match the provenance record and verified capture.
- reviewer_id, reviewer_role, and timezone-aware reviewed_at.
- review_status: pending, accepted, rejected, or conflicted.
- source_identity_verified and original_document_confirmed boolean assertions.
- Positive page_count.
- attachment_inventory and reviewed_attachments arrays. The inventory must exactly match the named attachments in the provenance manifest; reviewed attachments must be a subset.
- fact_reviews, containing fact_name, positive one-based page_number, and exact_excerpt. Optional attachment_name identifies the inventoried annexure when the fact appears outside the main filing.
- attachment_page_counts, an object mapping any annexure cited by a fact review to its positive page count. Main-document facts use page_count.

## Acceptance rules

A review row with accepted status is accepted only when:

1. Event, source-record ID, URL, document type and SHA-256 match the verified capture.
2. The provenance document is P1, its own review status is accepted, and it records the original document and direct review.
3. The reviewer confirms source identity and the original document.
4. The main-document page count is positive; each annexure-scoped fact names an inventoried attachment with a positive attachment page count, and every referenced page is within its respective document.
5. The attachment inventory exactly matches the provenance inventory, and every inventoried attachment is marked reviewed.
6. The reviewed fact/page/excerpt/attachment tuples exactly match the provenance fact links for that evidence document.

A pending, rejected or conflicted review is retained as a review record but is not included in accepted_evidence_ids. Missing P1 review rows, invalid lineage, incomplete attachment review, or fact excerpt drift fail closed. P2-P5 evidence cannot be promoted through this loader.

## Example

~~~json
{
  "schema_version": 1,
  "reviews": [
    {
      "evidence_id": "EV-001-DOC-1",
      "event_id": "EV-001",
      "source_record_id": "stage3c-source-id",
      "source_url": "https://exchange.example/filing.pdf",
      "document_type": "exchange_filing_pdf",
      "content_sha256": "<64-character SHA-256 from verified capture>",
      "reviewer_id": "operator-id",
      "reviewer_role": "corporate-actions-reviewer",
      "reviewed_at": "2026-11-06T12:00:00+05:30",
      "review_status": "accepted",
      "source_identity_verified": true,
      "original_document_confirmed": true,
      "page_count": 3,
      "attachment_inventory": ["annexure-a.pdf"],
      "reviewed_attachments": ["annexure-a.pdf"],
      "attachment_page_counts": {"annexure-a.pdf": 4},
      "fact_reviews": [
        {
          "fact_name": "appointment_term",
          "page_number": 2,
          "exact_excerpt": "Exact clause transcribed from the reviewed page.",
          "attachment_name": "annexure-a.pdf"
        }
      ]
    }
  ]
}
~~~

The example is illustrative only. It is not evidence for any real event. Never copy placeholder IDs, hashes or excerpts into a production manifest.

## API

~~~python
from pathlib import Path

from nse_swing_bot.events.review import load_evidence_review_manifest

result = load_evidence_review_manifest(
    review_path=Path("review-manifest.json"),
    evidence_manifest_path=Path("evidence-manifest.json"),
    expected_event_sources={"EV-001": "stage3c-source-id"},
    capture_manifests={"EV-001-DOC-1": Path("archive/capture-manifest.json")},
)

# Informational only; this does not score or promote an event.
print(result.accepted_evidence_ids)
~~~

Use evaluate_reviewed_event_evidence for the admission decision after loading the review manifest. It filters the provenance bundle to accepted operator-review IDs before delegating to the existing fail-closed evaluate_event_evidence policy. A pending, rejected, conflicted or missing review therefore cannot satisfy a required fact even if an upstream provenance record was mistakenly marked accepted.

~~~python
from nse_swing_bot.events.review import (
    evaluate_reviewed_event_evidence,
    load_evidence_review_manifest,
)

reviewed = load_evidence_review_manifest(
    review_path=Path("review-manifest.json"),
    evidence_manifest_path=Path("evidence-manifest.json"),
    expected_event_sources={"EV-001": "stage3c-source-id"},
    capture_manifests={"EV-001-DOC-1": Path("archive/capture-manifest.json")},
)
admission = evaluate_reviewed_event_evidence(canonical_event, reviewed)
~~~

This bridge does not modify source data, set legacy statuses, create canonical events, score signals, or authorize trades. No command-line wrapper or automatic promotion is provided in this stage.



## Annexure-level fact references (Stage 4B-8)

When a policy fact is supported by an annexure rather than the main filing, set attachment_name on both the provenance fact link and the operator fact review. The attachment must appear in the declared inventory and be marked reviewed. Supply its positive page count in attachment_page_counts; the loader checks the excerpt page against that annexure's page count, not the main PDF's page count. Facts without attachment_name continue to refer to the main source document.
