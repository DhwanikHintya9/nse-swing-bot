# Stage 4B-5 — Capture integrity verification

The capture utility in Stage 4B-4 writes a local source archive and a sibling JSON manifest. This stage adds a read-only verifier:

```bash
python scripts/verify_event_source_capture.py --manifest ./data/corporate_events/source_archive/EV-THANGAMAYL-01_<digest>.capture.json
```

The verifier checks the manifest schema and capture mode, event/source identifiers, absolute HTTP(S) source URL, timezone-aware capture timestamp, safe archive basename, positive byte length, and lowercase SHA-256. It then streams the archived file and independently recomputes both byte length and SHA-256.

A successful result means only that the archived bytes match the capture manifest. It does **not** establish that the URL is authentic, the file is an original NSE/issuer document, the document is complete, annexures were reviewed, excerpts support event facts, or evidence is accepted as P1. Those remain separate operator review and provenance-ingestion steps.

The verifier rejects path traversal, symlinked archive objects, missing files, malformed metadata, and altered bytes. It does not modify either the archive or manifest.
