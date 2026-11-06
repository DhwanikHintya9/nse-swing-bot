# Stage 4B-9 — Safe ZIP filing-package inventory

The ZIP inventory utility inspects a locally captured ZIP package without extracting members. It first runs the existing capture-manifest verifier, then records the member list, uncompressed/compressed lengths, CRC-32 and SHA-256 for each regular file member. Every member hash is bound to the verified parent archive SHA-256, event ID and Stage 3C source-record ID.

## Safety checks

- Requires a verified capture manifest and a captured archive with a .zip extension.
- Rejects absolute paths, parent traversal, dot components, backslashes, drive-prefixed names, ambiguous repeated separators and duplicate member names.
- Rejects encrypted members and Unix symlink entries.
- Enforces configurable member-count, per-member size, total uncompressed size and compression-ratio limits before reading member contents.
- Streams each member to compute SHA-256; no archive member is extracted to the filesystem.
- Writes a new inventory manifest without overwriting an existing file.

Defaults: at most 500 ZIP entries, 100 MiB per file, 200 MiB total uncompressed content and a maximum compression ratio of 1000:1. These are defensive defaults, not a claim that all issuer ZIP packages fit within them. Operators may raise limits deliberately after assessing the archive and available resources.

## Usage

First capture the original ZIP using capture_source_bytes / scripts/capture_event_source.py, then verify the capture. Inventory it:

~~~bash
python scripts/verify_event_source_capture.py --manifest archive/EV-KIRLOSENG-03_<digest>.capture.json

python scripts/inventory_event_zip.py \
  --capture-manifest archive/EV-KIRLOSENG-03_<digest>.capture.json \
  --output archive/EV-KIRLOSENG-03_package-inventory.json
~~~

The output records each internal member's exact name and digest. It does not rewrite the parent ZIP, extract files, determine whether an internal PDF is an issuer original, or mark an attachment reviewed. If a member needs its own evidence record, it must be safely materialized for inspection, separately captured with an explicit parent-archive/member lineage extension, and reviewed. That workflow is intentionally not inferred by this inventory step.

## Evidence boundary

ZIP integrity and member hashes prove only that the inspected member bytes correspond to the captured package. They do not establish source authenticity, document completeness, attachment relevance, direct human review, P1 evidence status, event admission or signal eligibility. No event is promoted by this utility.
