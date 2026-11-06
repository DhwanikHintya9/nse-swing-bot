# Stage 4B-10 — Safe ZIP member capture and lineage

This step materializes one explicitly selected ZIP member only after verifying the parent capture and checking the selected member against the ZIP inventory. It does not extract the full package.

## Workflow

1. Capture the original exchange ZIP and verify its capture manifest.
2. Inventory the ZIP using Stage 4B-9.
3. Select the exact member name from the inventory.
4. Materialize one member:

```bash
python scripts/materialize_event_zip_member.py \
  --capture-manifest archive/EV-KIRLOSENG-03_<digest>.capture.json \
  --inventory archive/EV-KIRLOSENG-03_package-inventory.json \
  --member "path/inside/package.pdf" \
  --output-dir archive/members \
  --captured-at "2026-11-06T14:00:00+05:30"
```

The utility checks the inventory's event/source/archive linkage, exact member name, size, CRC-32 and SHA-256. It writes a child capture manifest that preserves the event ID, Stage 3C source-record ID and parent NSE URL, while explicitly labelling the document as an archive member. The child manifest points to the parent capture manifest and parent archive digest.

## Verification boundary

The normal capture verifier also verifies child lineage: parent archive integrity, matching event/source/URL, parent archive digest, exact member uniqueness, child byte digest/length and CRC. A child cannot be treated as an independently fetched NSE document. It inherits the parent ZIP's source URL and remains an archive member.

This establishes byte integrity and lineage only. It does not establish issuer authenticity, document completeness, attachment relevance, direct human review, P1 evidence status, event admission or signal eligibility. Operator review remains a separate required step. No event is promoted by this utility.
