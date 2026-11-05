# Stage 2 — Market data foundation

## Implemented

- Kite Connect adapter for NSE instrument-master retrieval and daily historical candles.
- NSE cash-equity instrument normalization, retaining instrument token and tick size from the current daily master.
- Official NSE Nifty 500 CSV acquisition with symbol-count validation, explicit effective date, source URL, and immutable dated snapshots.
- OHLCV integrity checks and optional expected-session validation against a caller-supplied exchange calendar.
- Append-only raw Parquet snapshots. Corrections are stored as a new snapshot; the latest captured value is selected when reading.
- Point-in-time corporate-action adjustment function requiring verified primary and secondary source references and explicit factors.

## Important operational boundaries

- The Kite client is injected. No API key, access token, login flow, or broker order method is included.
- Historical requests are sequential and chunked. A central rate-limit scheduler and retry policy remain a later infrastructure task; do not parallelize downloads.
- Kite's instrument token is treated as a current lookup key, not a permanent identity. Persist exchange + trading symbol as the durable key and retain dated instrument-master snapshots.
- The Nifty 500 downloader fails closed and never silently falls back to stale data. Its effective date is supplied by the caller and must match the source snapshot's actual effective date.
- Missing-session validation is only authoritative when an NSE trading calendar is supplied. Weekends alone are not a sufficient holiday calendar; special sessions must be explicitly recorded.
- Corporate-action factors are not guessed. An event without verified factors and both source references must be held for manual review.
- This stage does not change or invoke the original live bot.

## Next work

1. Add rate-limit scheduling, retry/backoff, sync checkpoints, and data-quality quarantine.
2. Add historical corporate-action event ingestion and independent factor verification.
3. Build point-in-time backtest datasets and exact universe membership history from dated official snapshots and change notices.


## Stage 3A — universe and calendar reliability

- Added a downloader for the official NSE Nifty 500 constituent CSV linked from the NSE index page.
- Every downloaded universe is validated against the official five-column NSE CSV schema, unique symbols and ISINs, and the current expected row count (501, verified against the NSE response on 2026-11-05). Snapshots retain company name, industry, security series, ISIN, effective date, and source URL. A future count change fails closed for review; it is not silently accepted.
- Index membership is kept separate from cash-equity strategy eligibility. `EQ`, `BE`, and `RR` source series are retained as supplied; downstream strategy filters must make an explicit eligibility decision rather than dropping non-`EQ` members during universe ingestion.
- Added an NSE trading-calendar loader for archived official holiday data exported to CSV. Each calendar has an explicit coverage range; requests outside that range fail closed. Special sessions require their own source reference and can include weekend Muhurat sessions.
- Calendar source provenance is retained with each holiday row. NSE currently publishes the holiday schedule as an official web table; this implementation ingests an operator-archived CSV export and deliberately does not scrape dynamic HTML or silently infer exchange holidays.
- Historical membership is not reconstructed by pretending the current list was always valid. Collect dated snapshots and official effective-date change notices before building exact membership intervals.
- The Nifty 500 download is an external network operation and has not been exercised against NSE from CI; tests use injected response bytes. A failed download must not replace a previously approved snapshot.


## Stage 3B — request reliability and data quarantine

- Added one shared, process-local Kite request pacer: historical candle calls are spaced at no more than 3 requests/second, quote calls at 1/second, and other endpoints at 10/second, matching the currently published Kite API limits.
- Added bounded retries for HTTP 429, HTTP 5xx, and recognized transient network exceptions. HTTP 400/403 and other non-transient client errors fail immediately. A 429 honors Retry-After when supplied; otherwise the conservative cooldown is 10 seconds.
- The 10-second fallback reflects Zerodha's published guidance for the throttling cooldown on repeated bad requests. The request pacing and retry settings should be rechecked against Kite's documentation before production rollout.
- Historical downloads can persist completed date chunks atomically and resume after interruption without refetching completed chunks. Checkpoints are local JSON and must be stored on durable storage; they are not a substitute for the append-only Parquet raw dataset.
- Invalid OHLCV responses are written to an immutable JSON quarantine record with symbol, requested range, capture time, validation reason, and raw rows. They are not written to the clean Parquet store.
- The default limiter is process-local and shared across adapter instances in one Python process. It does not coordinate multiple processes or machines. Before multi-worker production, replace it with a distributed limiter keyed by Kite API key (for example, Redis-backed) and add operational metrics/alerts.
- Retry logic is deliberately narrow: it does not retry invalid requests, expired sessions, permission failures, or unknown exceptions. No credentials, login, or order methods were added.
- The current test suite uses fake Kite clients and injected clocks/sleep functions. It does not contact Kite or require live credentials.


## Stage 3C — point-in-time corporate events and earnings gates

- Added a normalized event model for earnings dates, ordinary dividends, material corporate actions, and critical corporate actions. Each event retains an event ID, symbol, event date, timezone-aware announcement timestamp, title, primary and secondary source URLs, and verification status.
- Added strict CSV ingestion for an operator-reviewed normalized export. The expected columns are: `event_id,symbol,event_type,event_date,announced_at,title,source_primary,source_secondary,verification_status`. Event types and verification states are enumerated; malformed rows, missing provenance, naive timestamps, and unknown classifications fail closed.
- Added immutable timestamped JSON event snapshots. Each snapshot stores events and per-symbol coverage manifests with their source references, coverage range, capture time, and completeness flag. Existing snapshots are never overwritten.
- Entry gating fails closed when coverage is missing, incomplete, captured after the decision timestamp, starts too late, or does not extend through the five-calendar-day earnings window.
- Earnings announced and scheduled within the next five calendar days block new entries. Material and critical corporate actions within three calendar days block entries. Unverified or conflicting events in a relevant window require manual review and block entries. Ordinary cash dividends do not block entries.
- Historical evaluation is point-in-time: an event is invisible until its recorded announcement timestamp. This prevents future announcements leaking into backtests.
- This is an ingestion and policy layer, not a live exchange connector. Operators must archive/download official exchange records, normalize and independently verify them, and mark coverage complete only after reconciling the full symbol/date window. The code intentionally does not scrape dynamic NSE/BSE pages or infer a clean bill of health from an empty event list.
- NSE provides separate Corporate Actions, Announcements, Board Meetings, and Financial Results views. NSE's own corporate-filings page states that company-uploaded filing content is disseminated without NSE verifying its adequacy, accuracy, or veracity. Accordingly, an NSE row alone is not treated as independent verification; the second source must be reviewed and recorded. Official entry points: https://www.nseindia.com/companies-listing/corporate-filings-actions, https://www.nseindia.com/companies-listing/corporate-filings-announcements, https://www.nseindia.com/companies-listing/corporate-filings-financial-results, and https://www.bseindia.com/corporates.html.
- No live NSE/BSE ingestion, credential use, or broker interaction was performed. The CSV parser, policy, provenance validation, and snapshot persistence are covered with local tests. Exchange export layouts and event classification remain operator-controlled until stable official machine-readable specifications are confirmed.
