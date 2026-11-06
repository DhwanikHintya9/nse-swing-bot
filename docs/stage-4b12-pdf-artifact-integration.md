# Stage 4B-12 — Evidence-bound PDF artifact integration

Stage 4B-12 connects the read-only PDF inspection and exact-excerpt artifacts from Stage 4B-11 to the provenance fact links introduced in Stage 4B-3.

## Contract

Use `verify_pdf_artifact_bundle(...)` after loading the evidence manifest with `load_verified_evidence_manifest(...)`. For each P1 evidence record, supply:
- its PDF inspection JSON from `inspect_event_pdf.py`;
- one immutable excerpt verification JSON for every provenance fact link;
- a small operator-authored binding JSON for each excerpt.

Binding schema (one file per fact excerpt):

```json
{
  "schema_version": 1,
  "evidence_id": "EV-EXAMPLE-01",
  "fact_name": "appointment_term",
  "attachment_name": null,
  "inspection_manifest": "filing.pdf-inspection.json",
  "excerpt_manifest": "filing.excerpt-01.json"
}
```

Paths are relative to the binding JSON. Set `attachment_name` to the exact declared material attachment name when the fact comes from a named attachment; use null for the main filing. The evidence ID and fact name must match the provenance record exactly.

The verifier rechecks the exact excerpt against the captured PDF bytes, verifies capture lineage and PDF SHA-256, checks page number and page-text digest against the inspection manifest, and requires complete one-to-one coverage of the provenance fact links for that evidence record. A supplied excerpt manifest or hash is never trusted without recomputation.

## Limits and safety

- This validates artifact linkage and byte/text consistency; it does not establish issuer authenticity, document completeness, reviewer identity, or correct interpretation.
- Text extraction remains non-OCR and may omit scanned pages, tables, images, footnotes, or handwriting.
- Embedded PDF attachment names are not extracted or reviewed by this contract. Do not mark an attachment reviewed based only on a name-tree listing.
- Evidence review remains pending unless the separate operator-review manifest is complete and accepted.
- No automatic P1 classification, evidence acceptance, event promotion, scoring, or signal eligibility is performed.
