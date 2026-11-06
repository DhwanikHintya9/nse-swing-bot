# Stage 4D-5-1 — Historical OHLCV acquisition contract

## Status

**IMPLEMENTED — LIVE FIVE-SYMBOL ACQUISITION EXECUTED; SPECIAL-SESSION CALENDAR RECONCILIATION APPLIED; RE-RUN PENDING.**

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
- `src/nse_swing_bot/market_data/pilot.py` and `scripts/kite_read_only_pilot.py`: five-symbol, read-only pilot orchestration and local CLI.

The next implementation should extend these rather than create a second HTTP client, retry layer, checkpoint format, or raw store.

## Kite API constraints and assumptions

The official Kite historical API documents the `day` interval, date/time request parameters, and candle fields. It describes history as spanning “several years” but does not publish a guaranteed retention start date or a maximum daily request-window size. Therefore:

1. Do not encode an assumed multi-year retention guarantee.
2. Do not encode an undocumented maximum request-window size as a correctness rule.
3. Retain the repository's existing 365-calendar-day chunk default for the pilot; if Kite rejects a window, fail with the exact range and let the operator rerun with a smaller chunk size. Do not silently truncate or bisect in a way that loses request lineage.
4. Record the earliest returned candle and requested range for every symbol. A successful API response does not prove complete history.
5. Do not describe Kite historical candles as exchange-as-traded raw prices. Zerodha Support states that Kite historical OHLC is provider-adjusted for bonuses, splits, rights issues, spin-offs and extraordinary dividends at or above 2% of underlying market value. Ordinary dividends below that threshold are not included in the stated adjustment set. The public API reference does not expose per-candle adjustment factors or a versioned adjustment ledger. Therefore classify the downloaded series as **provider-adjusted, independently unreconciled**. Never apply a second adjustment blindly, and never label it split-and-dividend-adjusted for Stage 4D outcome labels without an independent action-by-action reconciliation and an explicit decision about ordinary dividends.

References:
- NSE 2025 Capital Market Segment holiday circular (NSE/CMTR/65587): https://nsearchives.nseindia.com/content/circulars/CMTR65587.pdf
- NSE 2026 official equity holiday page: https://www.nseindia.com/resources/exchange-communication-holidays
- NSE Capital Market Circular NSE/CMTR/72349 (2026-01-16), live equity trading on Sunday 2026-02-01 for Union Budget: https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf
- Kite historical data API: https://kite.trade/docs/connect/v3/historical/
- Official Python client method contract: https://kite.trade/docs/pykiteconnect/v4/
- Zerodha Support — Kite chart historical OHLC corporate-action adjustments: https://support.zerodha.com/category/trading-and-markets/charts-and-orders/charts/articles/kite-charts-not-matching-as-per-the-records-in-nse-or-bse

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
- Explicit `read_only=true`, `orders_endpoint_calls=0`, `production_eligible=false`, and `adjustment_status=provider_adjusted_unreconciled`.

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
- Explicit limitations: current token mapping is not a historical instrument identity; current Kite dump cannot alone prove historical symbol/ISIN continuity; Kite's provider adjustment policy is not independently reconciled and is not a substitute for the project's declared split-and-dividend adjustment convention.

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

- Added `src/nse_swing_bot/market_data/acquisition_manifest.py` with canonical JSON serialization, SHA-256 payload binding, required research-only safety fields, recursive rejection of credential-like field names, tamper verification, streaming file hashing, and atomic no-overwrite publication. The manifest requires `provider_adjusted_unreconciled` rather than implying exchange-raw prices.
- Added `src/nse_swing_bot/market_data/pilot.py` and `scripts/kite_read_only_pilot.py`. The runner refreshes the current NSE/EQ Kite instrument master, binds five explicitly selected EQ symbols to source ISINs, fetches sequential daily candles through the existing adapter, records per-symbol request/retry telemetry, reports missing/unexpected sessions, writes append-only Parquet snapshots, verifies read-back, and emits a SHA-256-bound immutable manifest.
- Mapping ambiguity fails closed and is recorded in the run manifest. Missing sessions are reported, never filled. Out-of-range and other candle-validation failures are quarantined. A pilot is accepted only when all five symbols have complete expected-session coverage, no unexpected/out-of-range dates, and verified Parquet read-back.
- Each symbol manifest entry records exact inclusive request chunk ranges, chunk completion state, and request/retry counters. The instrument-master request is separately counted. Counter fields are logical calls, attempts, retries, errors, and terminal failures.
- Extended `KiteRequestExecutor` with detached counters for logical calls, attempts, retries, errors, and terminal failures; existing pacing and retry behavior is unchanged.
- Added `tests/test_acquisition_manifest.py`, `tests/test_acquisition_pilot.py`, and request-telemetry coverage in `tests/test_market_data_reliability.py`. The CLI help is included in the no-credentials operational smoke tests.
- Added `data/market_calendar/nse-equity-holidays-2025-2026.csv`, sourced from the official NSE 2025 Capital Market Segment holiday circular and the official NSE 2026 equity holiday page. It covers the default rolling 12-month pilot window from 2025-11-06 through 2026-11-05. Muhurat sessions are retained as holiday dates in the source file and must be added back through explicit `--special-session` arguments if a requested pilot window includes them. The 2026-02-01 Sunday Union Budget live-trading session is not a regular weekday and is therefore added by the default pilot CLI from NSE circular NSE/CMTR/72349.
- CI on the preceding implementation head passed both push and PR workflows. Fresh checks for the latest test commit are running; no live Kite request has been made by CI or this implementation session.

## Next implementation sequence

1. Confirm CI on the current head.
2. Obtain/assemble an official NSE equity session calendar covering the selected 12-month pilot window, with special sessions explicitly sourced.
3. The operator runs the local five-symbol pilot using local Kite credentials and shares only the generated non-secret manifest/report plus sanitized failures.
4. Review the pilot evidence before authorizing historical-depth probing or 500-symbol ingestion.

## Safety

This stage is research-data acquisition only. It does not modify Phase 1 signals, indicators, entry/exit rules, strategy configuration, trade management, or broker routing. No live trading is enabled.


## Local operator command

The CLI defaults to the five-symbol EQ pilot `RELIANCE,HDFCBANK,INFY,SUNPHARMA,LT`, the archived 2026-09-30-effective Nifty 500 source, and the combined official 2025-2026 NSE equity holiday file. Its default window is 2025-11-06 through 2026-11-05, with declared calendar coverage from 2025-01-01 through 2026-12-31. It also automatically adds the official Sunday 2026-02-01 Union Budget trading session (NSE/CMTR/72349) to the expected session set. Override the calendar and coverage only when using another source snapshot; separately document any special session inside the requested interval.

Default pilot invocation (uses the archived 2025-2026 holiday file and default 12-month date window):

```bash
python scripts/kite_read_only_pilot.py
```

To override the window or calendar source, pass the corresponding `--from-date`, `--to-date`, `--calendar-csv`, `--calendar-source`, and coverage arguments. Do not extend declared calendar coverage beyond the dates supported by source evidence.

Optional `--special-session YYYY-MM-DD=SOURCE` arguments may be repeated. To use a different five-symbol EQ pilot, pass `--symbols SYMBOL1,SYMBOL2,SYMBOL3,SYMBOL4,SYMBOL5`. The command reads `KITE_API_KEY` and `KITE_ACCESS_TOKEN` from the local environment / Git-ignored `.env`; never paste them into chat or commit them. A nonzero exit code means the immutable manifest was written but the pilot failed its acceptance gate. Review that manifest and its quarantine references rather than rerunning blindly.
