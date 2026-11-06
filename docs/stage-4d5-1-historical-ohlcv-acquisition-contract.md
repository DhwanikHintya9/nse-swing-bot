# Stage 4D-5-1 — Historical OHLCV acquisition contract

## Status

**IN PROGRESS — MANIFEST FOUNDATION IMPLEMENTED; PILOT CLI AND RUNNER PENDING.**

This increment defines the acceptance contract for a read-only Kite daily-candle pilot. It does not claim that Kite data is adjusted, complete, or sufficient for the five-year study. It does not run broker orders or alter Phase 1.

## Objective and boundary

Build a repeatable, resumable local acquisition path for raw NSE cash-equity daily OHLCV. First prove the pipeline on a small, deterministic pilot; only then consider scaling to the historical universe.

In scope:

- Current Kite NSE instrument-master capture, retained as an immutable source snapshot.
- Explicit input mapping from approved universe symbol + ISIN to exactly one current Kite NSE cash-equity instrument token.
- Daily historical candles only, fetched sequentially through the existing `KiteMarketDataAdapter`.
- Existing request pacing, bounded retry, validated chunk checkpoints, OHLCV validation, quarantine, and append-only Parquet store.
- A new acquisition manifest binding the request, instrument identity, source snapshot, persisted candle snapshots, row/date coverage, and SHA-256 digests.
- A local operator-run pilot command. Credentials remain local environment variables / ignored `.env`; no credential values are written to manifests or logs.

Out of scope:

- Weekly candle fetching (weekly bars will be derived later from validated daily sessions, if required).
- Intraday candles, quotes, WebSockets, order APIs, portfolio simulation, and live trading.
- Corporate-action adjustment or any claim that Kite OHLCV is split/dividend adjusted.
- Historical universe reconstruction, event-coverage completion, and performance evaluation.
- Automatic substitution of current membership for historical membership.

## Existing implementation reuse

The repository already provides the core primitives:

- `KiteMarketDataAdapter`: sequential daily candle retrieval, date chunking, validation before checkpointing, and reuse of validated chunks.
- `KiteRequestExecutor`: process-local pacing and bounded transient-error retries.
- `JsonChunkCheckpointStore`: atomic resumable local chunks.
- `validate_daily_candles`: OHLCV integrity checks and optional expected-session checks.
- `ParquetCandleStore`: append-only raw snapshots; refuses timestamp collisions/overwrite.
- `MarketDataService`: instrument refresh, validation, quarantine, and persistence.
- `scripts/kite_read_only_ingest.py`: existing one-symbol smoke-test entry point.

The next implementation should extend these rather than create a second HTTP client, retry layer, checkpoint format, or raw store.

## Kite API constraints and assumptions

The official Kite historical API documents the `day` interval, date/time request parameters, and candle fields. It describes history as spanning “several years” but does not publish a guaranteed retention start date or a maximum daily request-window size. Therefore:

1. Do not encode an assumed multi-year retention guarantee.
2. Do not encode an undocumented maximum request-window size as a correctness rule.
3. Retain the repository's existing 365-calendar-day chunk default for the pilot; if Kite rejects a window, fail with the exact range and let the operator rerun with a smaller chunk size. Do not silently truncate or bisect in a way that loses request lineage.
4. Record the earliest returned candle and requested range for every symbol. A successful API response does not prove complete history.
5. Treat returned prices as **raw / adjustment basis unverified** until a separate, independently verified corporate-action process establishes the adjustment basis. Never label these candles split-and-dividend-adjusted merely because the API returned them.

References:
- Kite historical data API: https://kite.trade/docs/connect/v3/historical/
- Official Python client method contract: https://kite.trade/docs/pykiteconnect/v4/

## Pilot protocol

### Pilot universe

Use five liquid, currently listed Nifty 500 EQ-series cash equities selected from the archived, dated constituent source. Include RELIANCE as a repeatability check against the existing smoke test and select four additional symbols from distinct sectors. The input list must retain each symbol's ISIN, source universe snapshot identifier/hash, effective date, and selection rationale.

Do not include unresolved placeholder identities such as `DUMMYHEG`. Do not infer an ISIN from a company name. Each symbol must resolve to exactly one row in the approved universe input and exactly one NSE/EQ Kite instrument row. Ambiguous or missing mappings are quarantined before any candle request.

### Pilot date window

Start with a recent 12-month window that ends on the latest fully completed NSE session for which the operator has an approved calendar. The exact dates and calendar snapshot ID are supplied at run time and written to the manifest. This pilot validates acquisition mechanics and data integrity; it is not a five-year evaluation dataset.

After the recent-window pilot passes, run a separate historical-depth probe for the same five symbols using bounded date ranges, recording the actual earliest returned date per symbol. Do not assume all five symbols have identical retention.

### Execution

- Run locally with the user's own configured Kite credentials. Never request or transmit credentials in chat.
- Refresh and persist the Kite instrument master before candle acquisition.
- Resolve the input symbols to current instrument tokens and retain the full instrument rows used for the run.
- Fetch one symbol at a time. No parallel workers.
- Use the existing 365-day chunk default unless the operator explicitly supplies a smaller value.
- Validate each response before checkpointing or writing clean Parquet.
- Preserve invalid raw responses in quarantine; never coerce, fill, or silently drop invalid rows.
- Re-read every written Parquet snapshot and compare the persisted values with the validated fetched frame.
- Refuse overwrite. A rerun creates new timestamped snapshots and a new manifest; it does not mutate prior evidence.

## Acquisition manifest contract

Write one immutable JSON manifest per run under the local, Git-ignored market-data root. The manifest must contain:

### Run identity

- Schema version and manifest ID.
- Run start and completion timestamps in UTC.
- Tool/package version and Git commit SHA when available.
- Explicit `read_only=true`, `orders_endpoint_calls=0`, `production_eligible=false`, and `adjustment_status=unverified`.

### Source and request identity

- Provider = Kite Connect; endpoint class = historical; interval = `day`; continuous = false; OI = false.
- Requested start/end dates, chunk size, and expected NSE calendar snapshot ID/hash (if supplied).
- Instrument-master snapshot path, SHA-256, capture timestamp, and row count.
- For each symbol: exchange, trading symbol, ISIN, instrument token, instrument-master row fingerprint, universe source/effective date/hash, and mapping decision.

### Per-symbol result

- Requested date range and actual first/last returned dates.
- Row count, ordered columns, duplicate-date count, missing expected sessions, and out-of-range rows.
- Exact Parquet snapshot relative paths, byte sizes, row counts, and SHA-256 digests.
- Checkpoint chunk ranges and completion status; retries/failures summarized without secrets.
- Read-back verification result and numeric comparison tolerances.
- Quarantine references and reasons, if any.
- Explicit limitations: current token mapping is not a historical instrument identity; current Kite dump cannot alone prove historical symbol/ISIN continuity; no corporate-action adjustment has been applied or verified.

### Manifest integrity

- Canonical JSON serialization rules (UTF-8, sorted keys, stable separators) and SHA-256 of the manifest payload, excluding the digest field itself.
- Atomic write and no-overwrite behavior.
- A manifest with any unresolved mapping, failed chunk, failed read-back, or unaccounted expected session is marked `pilot_status=failed_or_incomplete`, not accepted.

## Pilot acceptance gate

The pilot passes only when all five symbols meet all of the following:

1. One-to-one symbol/ISIN/Kite instrument mapping is documented.
2. Every requested chunk is accounted for as fetched or explicitly failed; no silent truncation.
3. Every returned candle passes existing OHLCV validation.
4. Every expected NSE session in the supplied calendar is present, or every gap is explicitly reconciled and classified (for example, suspension or source limitation). No gap is auto-filled.
5. No duplicate dates or out-of-range rows remain.
6. Parquet read-back matches the validated fetched data.
7. Snapshot and manifest SHA-256 values recompute successfully.
8. No credentials or sensitive authentication material appear in artifacts or logs.
9. The run makes zero order endpoint calls.

A successful recent-window pilot authorizes only a separate historical-depth probe. It does not authorize 500-symbol bulk ingestion or research evaluation.

## Known gaps to resolve before bulk backfill

- Kite's current instrument dump is not a dated historical instrument master and the existing normalized schema does not itself establish ISIN lineage. The pilot input must bind ISIN to the archived universe source; longer-term identity continuity requires dated instrument-master evidence and exchange symbol-change records.
- The current Parquet store records capture timestamp and symbol in each partition but does not yet emit a complete acquisition manifest with checksums. Implement that manifest before treating the pilot as accepted.
- Existing expected-session validation detects missing sessions but does not classify why they are missing. The pilot report must expose gaps for operator reconciliation rather than claim every missing candle is a data error.
- Kite's public historical API documentation does not specify an adjustment guarantee. Independent corporate-action factors and reconciliation remain mandatory.
- The historical retention depth is not guaranteed by the public documentation and must be measured empirically per symbol.

## Implementation progress

- Added `src/nse_swing_bot/market_data/acquisition_manifest.py` with canonical JSON serialization, SHA-256 payload binding, required research-only safety fields, recursive rejection of credential-like field names, tamper verification, streaming file hashing, and atomic no-overwrite publication.
- Added `tests/test_acquisition_manifest.py` for deterministic digests, tamper detection, safety-envelope enforcement, credential-field rejection, non-finite JSON rejection, and immutable file publication.
- CI is running for the current feature-branch head; results have not yet been confirmed.

## Next implementation sequence

1. Extend the local CLI to accept a five-symbol input file and a supplied calendar snapshot; keep the existing one-symbol command behavior intact.
2. Add mocked integration tests for successful multi-symbol pilot, mapping ambiguity, partial failure/resume, missing sessions, read-back mismatch, manifest tampering, and credential redaction.
3. Run and inspect CI. Do not call Kite from CI.
4. The operator runs the five-symbol pilot locally and shares only the generated non-secret manifest/report plus any sanitized failures.
5. Review the pilot evidence before authorizing historical-depth probing or 500-symbol ingestion.

## Safety

This stage is research-data acquisition only. It does not modify Phase 1 signals, indicators, entry/exit rules, strategy configuration, trade management, or broker routing. No live trading is enabled.
