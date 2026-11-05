# Stage 3 operational acceptance

This document separates automated/code-level validation from live operational acceptance. Passing CI does not imply that external NSE, Kite, or corporate-event workflows have been exercised.

## Current status — checked 2026-11-05

| Area | Evidence completed | Remaining acceptance |
|---|---|---|
| NSE Nifty 500 source | User successfully ran `scripts/refresh_nifty500.py` from the Windows deployment environment for effective date `2026-09-30`. The resulting 501-row snapshot exactly matches the archived raw NSE capture across symbol, company name, industry, series, and ISIN; both symbol-difference sets are empty. The source's 27 additions are present and all 27 exclusions are absent. | Manually verify the source-data anomaly `DUMMYHEG` before allowing it into a tradable universe; preserve the archived source row without silently editing it. |
| NSE trading calendar | Archived the 16 weekday equity holidays shown by NSE on 2026-11-05. Added the 2026-11-08 Muhurat session separately using NSE Circular NSE/CMTR/76941. Calendar unit tests cover the special weekend session and 2026-11-10 holiday. | Re-archive the official calendar when extending coverage beyond 2026. |
| Kite authentication and request control | User successfully completed the Kite login/request-token exchange using the prototype `bot.py` and confirmed the session became active. User then checked Kite and reported no orders, positions, or GTTs from that run. Unit tests cover pacing, retry/backoff, Retry-After, shared 429 cooldown, and malformed data handling. | Complete the dedicated read-only smoke test for profile authentication, NSE instrument-master normalization, and historical candles. A Kite Connect plan with market-data access is required; Zerodha does not provide a sandbox. Keep credentials local and never paste them into chat or commit them. |
| Historical candle ingestion | Unit tests cover chunking, validated checkpoints, resume after interruption, cache revalidation, and quarantine. | Verify one or more read-only historical requests against the intended Kite account and compare the stored candles with the returned source payload. |
| Corporate events / earnings | Normalized CSV ingestion, independent-source checks, point-in-time visibility, coverage fail-closed behavior, and entry gates are covered by tests. | No complete operator-reviewed event archive has been reconciled across the full 501-symbol universe and required date range. Do not mark event coverage complete or enable entry decisions based on an empty event file. |
| CI | Latest verified PR workflow run on commit `5a2697e6e1c7e4a16379f6bd880a265634ab26bf` completed successfully. | Recheck CI after the current safety and local-authentication changes. |

## Safe Kite authentication and smoke-test sequence

Do not run the prototype `bot.py` to obtain a token. It has been changed to paper-only mode, but the dedicated helper below is the intended authentication path. The helper uses the existing `ZERODHA_API_KEY` and `ZERODHA_API_SECRET` values in the local `.env`, prompts for the temporary request token without echoing it, exchanges it for an access token, and saves the API key/access token into the Git-ignored local `.env`. It never prints the access token.

From Command Prompt, run each command separately:

```cmd
python -m pip install -e .
python scripts/kite_read_only_login.py
```

Open the printed Kite login URL in a browser, complete login, and paste the redirected `request_token` into the hidden terminal prompt. Do not copy it into chat. Then run:

```cmd
python scripts/kite_read_only_smoke.py --symbol RELIANCE --from-date 2026-11-02 --to-date 2026-11-04
```

The smoke script loads the local `.env` and calls profile, NSE instruments, and daily historical data only. It never calls order endpoints. A successful run prints the authentication result, normalized instrument count, candle count, returned date range, and `Order endpoints called: 0`.

The `.env` file is Git-ignored. Do not commit it, upload it, or paste its contents into chat. If credentials were exposed, rotate/revoke them before creating a new local session.

## Completed NSE deployment validation

On 2026-11-05, the user installed the package in editable mode, ran the NSE downloader for effective date `2026-09-30`, and saved `data/universe/nifty500-effective-2026-09-30.csv`. A local pandas reconciliation returned `Exact match: True`, 501 archived rows, 501 downloaded rows, `Only archived: []`, and `Only downloaded: []` for `symbol`, `company_name`, `industry`, `series`, and `isin_code`. The generated CSV was checked for the expected seven columns, nonblank required fields, unique symbols and ISINs, effective date `2026-09-30`, and series counts of 496 EQ, 2 BE, and 3 RR.

**Source-data exception:** both the archived raw NSE capture and normalized downloader output contain `DUMMYHEG` / `Dummy HEG Ltd.` / ISIN `DUM545A01024` (series `EQ`). This placeholder-like identity was not introduced by normalization. Preserve the raw source faithfully, but quarantine or manually verify the instrument identity before it can be considered tradable.

The original downloader command was:

```cmd
python scripts/refresh_nifty500.py --effective-date 2026-09-30 --output-dir data
```

The downloader uses the official NSE endpoint, browser-compatible headers, a 60-second timeout, and bounded transient retries. It writes an immutable normalized snapshot under `data/universe/`; an existing dated snapshot is never overwritten. Do not overwrite the already reconciled dated snapshot.

## Importing reviewed corporate-event coverage

Use the templates in `data/corporate_events/` to prepare the reviewed event list and one coverage row per symbol. Generate a complete worksheet for the archived 501-symbol universe first. Every row starts with blank source references and `complete=false`:

```cmd
python scripts/create_event_coverage_template.py --universe data/universe/source/nse-nifty500-captured-2026-11-05.csv --covered-from 2026-09-30 --covered-through 2026-11-30 --captured-at "2026-11-05T15:30:00+05:30" --output data/corporate_events/coverage-reviewed.csv
```

Fill and independently review both source references for every symbol. Set `complete=true` only after the stated symbol/date range has actually been reconciled.

```cmd
python scripts/import_corporate_events.py --events data/corporate_events/events-reviewed.csv --coverage data/corporate_events/coverage-reviewed.csv --universe data/universe/source/nse-nifty500-captured-2026-11-05.csv --output-dir data/corporate_events/snapshots --captured-at "2026-11-05T15:30:00+05:30" --require-complete
```

The import rejects missing or unexpected coverage symbols, event symbols outside the selected universe, duplicate universe/coverage symbols, invalid provenance, and incomplete coverage when `--require-complete` is set. If incomplete coverage is intentionally imported without that flag, the event gate still blocks entries for those symbols.

## Stage 3 exit criteria

Stage 3 operational acceptance is complete only when:
- [x] The application-level NSE downloader has been exercised successfully from the deployment network and its 501-row snapshot exactly reconciled to the archived official NSE source capture and official effective-date notice. The `DUMMYHEG` source-data anomaly remains a separate tradability-review exception.
- [ ] The dedicated read-only Kite smoke test succeeds and the expected instrument/candle data is persisted.
- [ ] Corporate-event coverage has been reconciled for the universe and date range required by the backtest/strategy, with independently verified sources.
- [ ] CI is green on the final Stage 3 head.

Until those criteria are met, Stage 4 remains gated. The Stage 3 PR stays draft and unmerged; `master` remains untouched.
