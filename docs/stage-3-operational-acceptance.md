# Stage 3 operational acceptance

This document separates automated/code-level validation from live operational acceptance. Passing CI does not imply that external NSE, Kite, or corporate-event workflows have been exercised.

## Current status — checked 2026-11-05

| Area | Evidence completed | Remaining acceptance |
|---|---|---|
| NSE Nifty 500 source | User-side download of the configured NSE CSV succeeded with HTTP 200 / `text/csv`. The raw CSV is archived. Its 2026-09-30 effective date is grounded in NSE Indices' August 10 replacement notice. All 27 additions are present and all 27 exclusions are absent. | Execute the application downloader from the intended deployment network and compare the returned source count/schema with the archived 501-row capture. |
| NSE trading calendar | Archived the 16 weekday equity holidays shown by NSE on 2026-11-05. Added the 2026-11-08 Muhurat session separately using NSE Circular NSE/CMTR/76941. Calendar unit tests cover the special weekend session and 2026-11-10 holiday. | Re-archive the official calendar when extending coverage beyond 2026. |
| Kite request control | Unit tests cover pacing, retry/backoff, Retry-After, shared 429 cooldown, and malformed data handling. The current Kite documentation confirms 1 quote request/sec, 3 historical candle requests/sec, and 10 requests/sec for other endpoints. | No live Kite request has been made. Zerodha does not provide a sandbox. Run read-only smoke tests only after a valid Kite Connect subscription and local credentials are configured. Do not put credentials in the repository or chat. |
| Historical candle ingestion | Unit tests cover chunking, validated checkpoints, resume after interruption, cache revalidation, and quarantine. | Verify one or more read-only historical requests against the intended Kite account and compare the stored candles with the returned source payload. |
| Corporate events / earnings | Normalized CSV ingestion, independent-source checks, point-in-time visibility, coverage fail-closed behavior, and entry gates are covered by tests. | No complete operator-reviewed event archive has been reconciled across the full 501-symbol universe and required date range. Do not mark event coverage complete or enable entry decisions based on an empty event file. |
| CI | CI run #223 passed on code head `8a32daf`: 78 tests and Ruff. | CI must pass on the current head after every subsequent code change. |

## Safe live-test sequence

1. From the intended deployment network, run the NSE downloader with effective date `2026-09-30`. Compare the five source columns, 501-row observed baseline, and symbol/ISIN uniqueness with the archived source capture. Do not replace the archived snapshot if the source count or schema changes unexpectedly.
2. Configure Kite credentials locally through environment variables or a secret manager. Never commit or paste API secrets or access tokens.
3. Use read-only Kite endpoints only for the smoke test: profile/session validation, instrument master retrieval, and a small historical candle range. Do not place, modify, or cancel orders.
4. Archive official event records and independent company/secondary references. Normalize and review them before setting any per-symbol coverage manifest to complete.
5. Keep the entry gate closed for symbols with missing, incomplete, stale, late, unverified, or conflicting event coverage.

## Importing reviewed corporate-event coverage

Use the templates in `data/corporate_events/` to prepare the reviewed event list and one coverage row per symbol. Then validate the files against the archived NSE source universe and write an immutable snapshot:

```powershell
python scripts/import_corporate_events.py `
  --events data/corporate_events/events-reviewed.csv `
  --coverage data/corporate_events/coverage-reviewed.csv `
  --universe data/universe/source/nse-nifty500-captured-2026-11-05.csv `
  --output-dir data/corporate_events/snapshots `
  --captured-at "2026-11-05T15:30:00+05:30" `
  --require-complete
```

The import rejects missing or unexpected coverage symbols, event symbols outside the selected universe, duplicate universe/coverage symbols, invalid provenance, and incomplete coverage when `--require-complete` is set. If incomplete coverage is intentionally imported without that flag, the event gate still blocks entries for those symbols.

## Stage 3 exit criteria

Stage 3 operational acceptance is complete only when:
- The application-level NSE downloader has been exercised successfully from the deployment network and the downloaded snapshot has been reconciled to an official effective-date notice.
- Read-only Kite smoke tests succeed with valid credentials and the expected instrument/candle data is persisted.
- Corporate-event coverage has been reconciled for the universe and date range required by the backtest/strategy, with independently verified sources.
- CI is green on the final Stage 3 head.

Until those criteria are met, Stage 4 remains gated. The Stage 3 PR stays draft and unmerged; `master` remains untouched.
