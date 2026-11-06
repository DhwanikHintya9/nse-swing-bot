# Stage 4B-11 — Read-only PDF inspection and exact excerpts

Stage 4B-11 adds bounded, read-only inspection for captured PDF bytes. The capture verifier runs first, including parent ZIP/member lineage verification for archive-member PDFs.

## Inspect a captured PDF

```bash
python scripts/inspect_event_pdf.py \
  --capture-manifest archive/<event>.capture.json \
  --output archive/<event>.pdf-inspection.json
```

The immutable JSON report records:
- capture/event/source linkage, PDF byte length and SHA-256;
- PDF version, page count and selected document metadata fields;
- per-page extractable-text presence, character count and text SHA-256;
- bookmark titles and page numbers;
- embedded attachment names, occurrences, byte lengths and SHA-256 digests.

Embedded attachment names are read from the PDF name tree only; embedded streams are not decompressed or extracted. Limits default to 250 MiB per PDF, 5,000 pages and 500 embedded attachment names. The name-tree depth is capped at 32. These limits can be tightened using CLI options.

## Verify an exact excerpt

After inspecting the PDF, an operator can verify an exact quotation against a specific one-based page:

```bash
python scripts/verify_pdf_excerpt.py \
  --capture-manifest archive/<event>.capture.json \
  --page 2 \
  --excerpt "appointed for a term of five years" \
  --output archive/<event>.excerpt-01.json
```

The verifier requires an exact substring match on the selected page. It does not normalize whitespace or punctuation. The output binds the excerpt to the captured PDF SHA-256, event ID, Stage 3C source-record ID, source URL, page number, page-text digest and excerpt digest. The output is immutable and explicitly remains pending operator review.

## Important limitations

- Text extraction is not OCR. Scanned pages, images, handwriting, tables, layout and footnotes may be absent or misread.
- PDF metadata and bookmarks are document-provided labels, not proof of issuer identity or annexure completeness.
- An embedded attachment inventory is not an annexure inventory for every filing; external ZIP members remain separate captured documents.
- An exact text match proves that the text layer contains the excerpt, not that the excerpt is materially complete or correctly interpreted.
- No tool in this stage sets P1, accepts an evidence record, promotes an event, or enables signal eligibility. Human/operator review and the existing fail-closed evidence gate remain mandatory.
