# Stage 3 operational acceptance

This document separates automated/code-level validation from live operational acceptance. Passing CI does not imply that external NSE, Kite, or corporate-event workflows have been exercised.

## Current status — checked 2026-11-05

| Area | Evidence completed | Remaining acceptance |
|---|---|---|
| NSE Nifty 500 source | User successfully ran `scripts/refresh_nifty500.py` from the Windows deployment environment for effective date `2026-09-30`. The resulting 501-row snapshot exactly matches the archived raw NSE capture across symbol, company name, industry, series, and ISIN; both symbol-difference sets are empty. The source's 27 additions are present and all 27 exclusions are absent. | Manually verify the source-data anomaly `DUMMYHEG` before allowing it into a tradable universe; preserve the archived source row without silently editing it. |
| NSE trading calendar | Archived the 16 weekday equity holidays shown by NSE on 2026-11-05. Added the 2026-11-08 Muhurat session separately using NSE Circular NSE/CMTR/76941. Calendar unit tests cover the special weekend session and 2026-11-10 holiday. | Re-archive the official calendar when extending coverage beyond 2026. |
| Kite request control | Unit tests cover pacing, retry/backoff, Retry-After, shared 429 cooldown, and malformed data handling. The current Kite documentation confirms 1 quote request/sec, 3 historical candle requests/sec, and 10 requests/sec for other endpoints. | No live Kite request has been made. Zerodha does not provide a sandbox. Run read-only smoke tests only after a valid Kite Connect subscription and local credentials are configured. Do not put credentials in the repository or chat. |
| Historical candle ingestion | Unit tests cover chunking, validated checkpoints, resume after interruption, cache revalidation, and quarantine. | Verify one or more read-only historical requests against the intended Kite account and compare the stored candles with the returned source payload. |
| Corporate events / earnings | Normalized CSV ingestion, independent-source checks, point-in-time visibility, coverage fail-closed behavior, and entry gates are covered by tests. | No complete operator-reviewed event archive has been reconciled across the full 501-symbol universe and required date range. Do not mark event coverage complete or enable entry decisions based on an empty event file. |
| CI | CI run #271 passed on head `8b3bdcc`: 88 tests and Ruff across `src`, `tests`, and `scripts`. | Recheck CI for the latest documentation commit. |

## Safe live-test sequence

1. **Completed on 2026-11-05 from the user's Windows deployment environment:** installed the package in editable mode, ran the NSE downloader for effective date `2026-09-30`, and saved `data/universe/nifty500-effective-2026-09-30.csv`. A local pandas reconciliation returned `Exact match: True`, 501 archived rows, 501 downloaded rows, `Only archived: []`, and `Only downloaded: []` for `symbol`, `company_name`, `industry`, `series`, and `isin_code`. The generated CSV was also checked for the expected seven columns, nonblank required fields, unique symbols and ISINs, effective date `2026-09-30`, and series counts of 496 EQ, 2 BE, and 3 RR.

   **Source-data exception:** both the archived raw NSE capture and the normalized downloader output contain `DUMMYHEG` / `Dummy HEG Ltd.` / ISIN `DUM545A01024` (series `EQ`). This placeholder-like identity was not introduced by normalization. Preserve the raw source faithfully, but quarantine or manually verify the instrument identity before it can be considered tradable.

   The original execution command was:

   ```powershell
   python scripts/refresh_nifty500.py --effective-date 2026-09-30 --output-dir data
   ```

   The downloader uses the official NSE endpoint, browser-compatible headers, a 60-second timeout, and bounded transient retries. It writes an immutable normalized snapshot under `data/universe/`; an existing dated snapshot is never overwritten. Do not overwrite the already reconciled dated snapshot.
2. Configure Kite credentials locally through environment variables or a secret manager. Never commit or paste API secrets or access tokens.

   On PowerShell, set them only in the local shell, then run the read-only smoke test:

   ```powershell
   $env:KITE_API_KEY = "<your-api-key>"
   $env:KITE_ACCESS_TOKEN = "<your-access-token>"
   python scripts/kite_read_only_smoke.py --symbol RELIANCE --from-date 2026-11-02 --to-date 2026-11-04
   Remove-Item Env:KITE_API_KEY
   Remove-Item Env:KITE_ACCESS_TOKEN
   ```

   The script calls profile, NSE instruments, and daily historical data only. It never calls order endpoints. A Kite Connect plan with market-data access is required; there is no sandbox.
3. Use read-only Kite endpoints only for the smoke test: profile/session validation, instrument master retrieval, and a small historical candle range. Do not place, modify, or cancel orders.
4. Archive official event records and independent company/secondary references. Normalize and review them before setting any per-symbol coverage manifest to complete.
5. Keep the entry gate closed for symbols with missing, incomplete, stale, late, unverified, or conflicting event coverage.

## Importing reviewed corporate-event coverage

Use the templates in `data/corporate_events/` to prepare the reviewed event list and one coverage row per symbol. Then validate the files against the archived NSE source universe and write an immutable snapshot:

Generate a complete worksheet for the archived 501-symbol universe first. Every row starts with blank source references and `complete=false`:

```powershell
python scripts/create_event_coverage_template.py `
  --universe data/universe/source/nse-nifty500-captured-2026-11-05.csv `
  --covered-from 2026-09-30 `
  --covered-through 2026-11-30 `
  --captured-at "2026-11-05T15:30:00+05:30" `
  --output data/corporate_events/coverage-reviewed.csv
```

Fill and independently review both source references for every symbol. Set `complete=true` only after the stated symbol/date range has actually been reconciled.

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
- [x] The application-level NSE downloader has been exercised successfully from the deployment network and its 501-row snapshot exactly reconciled to the archived official NSE source capture and the official effective-date notice. The `DUMMYHEG` source-data anomaly remains a separate tradability-review exception.
- Read-only Kite smoke tests succeed with valid credentials and the expected instrument/candle data is persisted.
- Corporate-event coverage has been reconciled for the universe and date range required by the backtest/strategy, with independently verified sources.
- CI is green on the final Stage 3 head.

Until those criteria are met, Stage 4 remains gated. The Stage 3 PR stays draft and unmerged; `master` remains untouched.
