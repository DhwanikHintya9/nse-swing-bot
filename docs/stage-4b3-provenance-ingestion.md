# Stage 4B-3 — Evidence provenance ingestion

The `nse_swing_bot.events.provenance` module loads an operator-authored JSON manifest and builds an event-to-fact-to-evidence map. It is read-only: it does not fetch source URLs, calculate hashes for missing source files, alter legacy triage rows, or admit events to the signal pipeline.

## Manifest contract

Schema version is `1`. The root object contains `documents` and `fact_links` arrays.

Each document requires:
- `evidence_id`, `event_id`, and the reconciled `source_record_id`
- `document_type`, absolute HTTP(S) `source_url`, `source_tier`, and `review_status`
- timezone-aware `retrieved_at`; timezone-aware `published_at` when known (otherwise null)
- `content_sha256` of the archived source bytes
- `original_document`, `directly_reviewed`, `material_attachments_required`, and `material_attachments_reviewed`
- `document_excerpt`

Each fact link requires `event_id`, `fact_name`, `evidence_id`, positive one-based `page_number`, and the exact `exact_excerpt` supporting that fact.

The caller supplies `expected_event_sources`, mapping canonical event IDs to the reconciled Stage 3C source-record IDs. Unknown events, source-ID mismatches, duplicate evidence IDs/links, cross-event links, invalid timestamps, missing excerpts/pages, and malformed evidence classifications fail closed.

## Evidence policy

- P1 still requires the original document, direct review, a captured SHA-256, and review of required material attachments. The evidence contract additionally requires accepted review status and a non-empty excerpt before admission.
- P2-P5 remain attachable for provenance and research, but cannot satisfy production fact requirements.
- Evidence is scoped to a canonical event, not merely a symbol. Different DABUR disclosures therefore have separate evidence states.
- A document's general excerpt is retained on the evidence record; each fact link separately stores its own exact excerpt and page.
- The loader does not infer P1 from Stage 3C `verification_status`, queue status, or narrative `evidence_basis`.

## Example shape

```json
{
  "schema_version": 1,
  "documents": [
    {
      "evidence_id": "EV-001-DOC-1",
      "event_id": "EV-001",
      "source_record_id": "stage3c-record-id",
      "document_type": "exchange_filing_pdf",
      "source_tier": "P1_DIRECT_PRIMARY_REVIEWED",
      "review_status": "accepted",
      "source_url": "https://exchange.example/filing.pdf",
      "retrieved_at": "2026-11-06T10:00:00+05:30",
      "published_at": "2026-11-06T09:30:00+05:30",
      "content_sha256": "<64-character SHA-256 of archived bytes>",
      "original_document": true,
      "directly_reviewed": true,
      "material_attachments_required": true,
      "material_attachments_reviewed": true,
      "document_excerpt": "Exact text transcribed from the reviewed filing."
    }
  ],
  "fact_links": [
    {
      "event_id": "EV-001",
      "fact_name": "appointment_term",
      "evidence_id": "EV-001-DOC-1",
      "page_number": 2,
      "exact_excerpt": "Exact clause supporting the appointment term."
    }
  ]
}
```

The example is a schema illustration only, not evidence for any real event. Never replace placeholders with guessed hashes or paraphrased excerpts. Events without complete source bytes and review artifacts remain pending/quarantined.
