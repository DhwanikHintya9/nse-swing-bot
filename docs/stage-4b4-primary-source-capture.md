# Stage 4B-4 — Primary-source capture queue

`data/corporate_events/evidence-capture-queue-v1.csv` is an operational intake queue for seven unresolved original source objects covering the high-priority Stage 3C quarantines. It is not an evidence manifest and cannot be passed to `load_evidence_manifest`.

## Capture policy

1. Retrieve the exact original NSE/issuer attachment bytes. Do not use a mirror's rendered text or a browser-extracted page as a substitute for the original bytes.
2. Preserve the source filename and URL, retrieval timestamp with timezone, byte length, SHA-256, MIME type, and immutable archive path.
3. Review the complete document, including every material annexure and any referenced resignation letter or ZIP member.
4. Record page-specific exact excerpts against individual canonical event facts. Keep event-to-source-record linkage exact.
5. Only after those checks may an operator create a P1 evidence manifest record with `review_status=accepted`. Otherwise attach the source at its correct lower tier or leave it pending.
6. Never change legacy Stage 3C `review_status` values as part of evidence capture.

## Queue coverage

| Capture item | Event(s) | Primary source object | Main unresolved requirement |
|---|---|---|---|
| CAP-THANGAMAYL-01 | EV-THANGAMAYL-01/02 | Board outcome PDF | Annexure A and exact appointment facts |
| CAP-KIRLOSENG-01 | EV-KIRLOSENG-01/02 | Appointment/ESOP PDF | Appointment and allotment annexure |
| CAP-KIRLOSENG-02 | EV-KIRLOSENG-03 | Resignation ZIP | Inspect original ZIP and resignation letter |
| CAP-DABUR-01 | EV-DABUR-06 | Joint internal-auditor PDF | Verify auditor appointment and period |
| CAP-SOBHA-01 | EV-SOBHA-01 | Board outcome PDF | Annexure A, consideration and conditions |
| CAP-CLEANMAX-01 | EV-CLEANMAX-01/02 | Board outcome PDF | Annexures A/B and full security/IFSC terms |
| CAP-AMBUJACEM-01 | EV-AMBUJACEM-01/02 | Board outcome PDF | Annexure B, consideration and conditions |

## Current capture result

The latest Stage 3C CSVs and migration snapshot are available in the conversation/library, but the original source PDFs/ZIPs listed above were not present as archived file attachments in the accessible file collection during this pass. Direct NSE archive retrieval attempts also did not return the original bytes. Consequently:

- No document SHA-256 has been fabricated.
- No exact excerpt or page citation has been fabricated.
- No P1 evidence record has been created or accepted from secondary reproductions.
- All seven capture items remain `awaiting_original_bytes`.
- The AMBUJACEM pair is explicitly flagged for duplicate review; no canonical IDs are merged automatically.

This queue is a transparent handoff from Stage 3C research into reproducible evidence capture. It does not promote, score, or otherwise change any event's production eligibility.

## Local byte-capture utility

The CLI `scripts/capture_event_source.py` archives a source file that has already been downloaded and inspected as the expected original exchange/issuer object. It performs no network request and does not parse or review the document.

Example (PowerShell or shell; supply the actual local file path and capture time):

```bash
python scripts/capture_event_source.py \
  --input ./incoming/THANGAMAYL_original.pdf \
  --archive-dir ./data/corporate_events/source_archive \
  --event-id EV-THANGAMAYL-01 \
  --source-record-id 49a714705c25dd3fff9d \
  --source-url https://nsearchives.nseindia.com/corporate/THANGAMAYL_04112026140903_OUTCOME_OF_MEETING_COVERING_LETTER.pdf \
  --document-type exchange_filing_pdf \
  --captured-at 2026-11-06T13:00:00+05:30
```

The command writes the original bytes under a SHA-256-derived immutable filename and a sibling JSON capture manifest containing byte length, SHA-256, original filename, source URL, event/source-record linkage and timezone-aware capture time. Existing capture paths are never overwritten. The manifest's review state is intentionally not accepted: direct review, attachment completeness and exact fact excerpts must still be recorded separately in the Stage 4B-3 evidence manifest.

For a document supporting multiple canonical events, create a separate event-linked capture record for each event while retaining the same source bytes/hash. Do not infer review acceptance from a successful byte capture.
