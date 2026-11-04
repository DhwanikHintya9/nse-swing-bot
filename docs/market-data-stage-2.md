# Stage 2 — Market data foundation

## Implemented

- Kite Connect adapter for NSE instrument-master retrieval and daily historical candles.
- NSE cash-equity instrument normalization, retaining instrument token and tick size from the current daily master.
- Explicit, source-attributed Nifty 500 constituent CSV ingestion. The file must be supplied from an official, reviewed constituent source; no synthetic or hardcoded universe is generated.
- OHLCV integrity checks and optional expected-session validation against a caller-supplied exchange calendar.
- Append-only raw Parquet snapshots. Corrections are stored as a new snapshot; the latest captured value is selected when reading.
- Point-in-time corporate-action adjustment function requiring verified primary and secondary source references and explicit factors.

## Important operational boundaries

- The Kite client is injected. No API key, access token, login flow, or broker order method is included.
- Historical requests are sequential and chunked. A central rate-limit scheduler and retry policy remain a later infrastructure task; do not parallelize downloads.
- Kite's instrument token is treated as a current lookup key, not a permanent identity. Persist exchange + trading symbol as the durable key and retain dated instrument-master snapshots.
- The universe loader does not claim to fetch the official Nifty 500 file automatically. A reviewed constituent snapshot and effective date must be provided.
- Missing-session validation is only authoritative when an NSE trading calendar is supplied. Weekends alone are not a sufficient holiday calendar.
- Corporate-action factors are not guessed. An event without verified factors and both source references must be held for manual review.
- This stage does not change or invoke the original live bot.

## Next work

1. Add a maintained NSE trading-calendar provider and official Nifty 500 constituent acquisition.
2. Add rate-limit scheduling, retry/backoff, sync checkpoints, and data-quality quarantine.
3. Add historical corporate-action event ingestion and independent factor verification.
4. Build point-in-time backtest datasets and universe membership history.


## Stage 3A — universe and calendar reliability

- Added a downloader for the official NSE Nifty 500 constituent CSV linked from the NSE index page.
- Every downloaded universe is validated for its Symbol column, uniqueness, and expected count (500 by default), then persisted as an immutable snapshot with an explicit effective date and source URL.
- Added an NSE trading-calendar loader for archived official holiday CSVs. The generated session index excludes declared holidays and can include explicitly declared special sessions, including weekend Muhurat sessions.
- Calendar source provenance is retained with each holiday row. The calendar deliberately does not scrape a dynamic HTML page or silently infer exchange holidays.
- Historical membership is not reconstructed by pretending the current list was always valid. Collect dated snapshots and official effective-date change notices before building exact membership intervals.
- The Nifty 500 download is an external network operation and has not been exercised against NSE from CI; tests use injected response bytes. A failed download must not replace a previously approved snapshot.
