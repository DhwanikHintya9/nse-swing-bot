# Stage 4D-5-4 — Point-in-time Nifty 500 membership evidence

## Decision

**Status: evidence-ingestion and conservative snapshot-diff tooling implemented; historical snapshot acquisition is not yet complete.**

The target interval remains 2021-11-06 through 2026-11-05. Membership is keyed by ISIN where available, with symbol, series and company name retained as dated attributes.

Today's official Nifty 500 CSV is only a current anchor. It must never be projected backwards as though it represented historical membership.

## Source inventory and evidence hierarchy

### Tier 1 — primary snapshot evidence

1. Current Nifty Indices constituent download:
   - Index page: https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-500
   - Verified current official CSV download URL (linked directly from the NSE Nifty 500 page): https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv
   - Nifty Indices CSV endpoint candidate: https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv (historical availability still to be verified)
2. Historical captures of the official CSV endpoints:
   - NSE endpoint historically used the filename `ind_cnx500list.csv` before the Nifty rebranding, and later `ind_nifty500list.csv`.
   - Nifty Indices endpoint candidate: `https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv`.
   - Wayback CDX discovery endpoint pattern:
     `https://web.archive.org/cdx/search/cdx?url=archives.nseindia.com/content/indices/ind_nifty500list.csv&output=json&filter=statuscode:200`
   - Repeat for the legacy `ind_cnx500list.csv` and Nifty Indices host. A Wayback capture is admissible only after the replayed payload is confirmed to be an original NSE/Nifty Indices CSV, and the capture timestamp, original URL and raw bytes are retained.
3. Existing repository anchor:
   - `data/universe/source/nse-nifty500-captured-2026-11-05.csv`
   - It is currently used by the read-only Kite probe and is marked effective 2026-09-30 in that workflow. It is not automatically promoted into the new evidence ledger: first verify its original download URL, exact capture time and raw source hash.

The official index page exposes the current constituent download and methodology, not a historical membership archive. The press-release archive is a separate change-evidence source.

### Tier 2 — official change evidence

- Nifty Indices press-release archive: https://www.niftyindices.com/press-release. The archive includes dated CNX 500 / Nifty 500 change notices (for example, older entries from 2010–2015); these are change evidence, not a complete daily membership series.
- NSE/Nifty Indices circulars and notices: https://www.nseindia.com/companies-listing/corporate-filings-actions

Use dated notices to resolve exact effective dates only when the notice explicitly names the Nifty 500 change and its effective date. Generic replacement notices must be parsed for the exact index section and verified against the actual attached document. A press-release archive is not assumed to capture all routine semi-annual market-cap reconstitutions.

### Tier 3 — discovery and corroboration only

- Monthly “Indices – Market Capitalisation & Weightage” ZIP reports:
  https://www.niftyindices.com/reports/monthly-reports
- Candidate historical archive pattern observed in public discussions:
  `https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMar2022.zip`
- Third-party PIT datasets, community posts and code repositories can help discover dates, filenames and gaps. They are not primary membership anchors and must not silently be copied into the accepted ledger.

A secondary source reports that the monthly ZIP archive included Nifty 500 through March 2022 and later files narrowed their index coverage. This is a lead to verify directly against the downloaded official ZIP contents, not an accepted completeness claim.

## Implementation added

- `src/nse_swing_bot/market_data/membership_evidence.py`
  - Validates source-attributed constituent CSVs.
  - Supports the official Nifty CSV headers: Company Name, Industry, Symbol, Series, ISIN Code.
  - Normalizes whitespace and case, validates Indian equity ISIN syntax, rejects duplicate ISINs and checks configurable row-count bounds (default 450–550; deliberately not exactly 500).
  - Retains the raw source bytes and SHA-256.
  - Writes a normalized ISIN-keyed CSV and a manifest with source URL, evidence URL, as-of date, capture timestamp, row count and content hashes.
  - Supports `official_snapshot` and `wayback_capture` only. Third-party reconstructions are discovery-only.
  - Reconciles adjacent snapshots by ISIN and reports observed additions/removals.
  - Leaves effective_date blank and marks it `unknown_between_snapshots`; it does not guess an effective date.
- `scripts/ingest_nifty500_snapshot.py`: ingest one source CSV.
- `scripts/reconcile_nifty500_snapshots.py`: reconcile all ingested snapshots.
- `tests/test_membership_evidence.py`: validates source restrictions, hashes, duplicates, and conservative diffs.

## Operator workflow

### 1. Collect official snapshot candidates

For each candidate date:
- Download the CSV from an official endpoint or a verified Wayback replay of an official endpoint.
- Keep the original downloaded file unchanged.
- Record the index as-of date separately from the download/capture timestamp.
- For Wayback, preserve both the original official URL and the exact replay URL with capture timestamp.
- Do not infer an as-of date from the date the browser downloaded the file. Use a publication/effective date supported by the source; if the page only gives a capture date, mark the snapshot date as the capture observation and document that limitation.

### 2. Ingest one snapshot

Example for an official snapshot (replace the example date and URL with the evidence actually obtained):

```powershell
python scripts/ingest_nifty500_snapshot.py `
  --csv .\downloads\nifty500-2022-03-31.csv `
  --as-of-date 2022-03-31 `
  --source-url https://archives.nseindia.com/content/indices/ind_nifty500list.csv `
  --evidence-url https://archives.nseindia.com/content/indices/ind_nifty500list.csv `
  --source-kind official_snapshot `
  --captured-at-utc 2026-11-06T10:00:00Z
```

Example for a verified Wayback replay:

```powershell
python scripts/ingest_nifty500_snapshot.py `
  --csv .\downloads\nifty500-wayback-2023-09-29.csv `
  --as-of-date 2023-09-29 `
  --source-url https://archives.nseindia.com/content/indices/ind_nifty500list.csv `
  --evidence-url "https://web.archive.org/web/20230929120000id_/https://archives.nseindia.com/content/indices/ind_nifty500list.csv" `
  --source-kind wayback_capture `
  --captured-at-utc 2026-11-06T10:00:00Z
```

The timestamps above are examples only. Supply the actual UTC capture timestamp and source-supported as-of date. Never reuse them as evidence for another file.

### 3. Reconcile collected snapshots

```powershell
python scripts/reconcile_nifty500_snapshots.py
```

Outputs:
- `data/universe/membership_reconciliation/observed-membership-changes.csv`
- `data/universe/membership_reconciliation/reconciliation-report.json`

The diff reports only that an ISIN was present in one observed snapshot and absent in the next. It does not claim when during that interval the change became effective. Changes that enter and leave between two snapshots can remain invisible; this is why dated official change notices and denser snapshots are required.

## Required next evidence collection

1. Obtain the exact official monthly ZIPs from June 2013 through March 2022 where available; inspect each ZIP's contents and record which files actually include Nifty 500.
2. Query Wayback CDX for both official CSV URL families, collect all useful 2021–2026 captures, and verify replay payloads before ingestion.
3. Acquire the current official CSV again with its exact source URL, effective date and capture timestamp, then compare it to the existing repository anchor.
4. Collect Nifty 500-specific press releases and replacement notices for every semi-annual review and ad-hoc event in the study interval.
5. Reconcile every snapshot diff to explicit notices where possible. Keep unresolved additions, removals, symbol changes, ISIN changes, mergers and demergers in separate queues.
6. Report temporal coverage gaps. Do not interpolate through a gap or use a third-party reconstruction as a substitute.
7. Obtain an independent review of the source payloads, parsed row counts and identity links.

## Acceptance criteria

Membership data is not accepted for research until:
- snapshots cover the full study interval with dated, source-verifiable anchors;
- raw bytes and hashes are retained for every snapshot;
- the actual index as-of date is distinguished from publication and capture timestamps;
- duplicate ISINs, malformed identifiers, symbol collisions and count anomalies are reviewed;
- every interval endpoint is supported by a snapshot or an explicit official change notice;
- unresolved ISIN migrations, mergers, demergers, delistings and symbol changes remain visible;
- every gap and every inferred interval is explicitly disclosed; and
- an independent review signs off on the resulting interval ledger.

## Safety and scope

- No Phase 1 strategy changes.
- No broker integration, order endpoint or live execution.
- No OHLCV bulk backfill, outcome labels or performance evaluation is authorized by this tooling.
- Corporate-action factor reconciliation remains a separate blocking gate.
