# Stage 3 operational acceptance

This document separates automated/code-level validation from live operational acceptance. Passing CI does not imply that external NSE, Kite, or corporate-event workflows have been exercised.

## Current status — checked 2026-11-05

| Area | Evidence completed | Remaining acceptance |
|---|---|---|
| NSE Nifty 500 source | User successfully ran `scripts/refresh_nifty500.py` from the Windows deployment environment for effective date `2026-09-30`. The resulting 501-row snapshot exactly matches the archived raw NSE capture across symbol, company name, industry, series, and ISIN; both symbol-difference sets are empty. The source's 27 additions are present and all 27 exclusions are absent. | Manually verify the source-data anomaly `DUMMYHEG` before allowing it into a tradable universe; preserve the archived source row without silently editing it. |
| NSE trading calendar | Archived the 16 weekday equity holidays shown by NSE on 2026-11-05. Added the 2026-11-08 Muhurat session separately using NSE Circular NSE/CMTR/76941. Calendar unit tests cover the special weekend session and 2026-11-10 holiday. | Re-archive the official calendar when extending coverage beyond 2026. |
| Kite authentication and request control | On 2026-11-05, the user completed the dedicated local login helper and the read-only smoke test passed: profile authentication OK, 10,281 NSE cash-equity instruments normalized, and 3 RELIANCE daily candles returned for 2026-11-02 through 2026-11-04. The test reported `Order endpoints called: 0`. Unit tests cover pacing, retry/backoff, Retry-After, shared 429 cooldown, and malformed data handling. | Persist and reconcile the returned candles through the application's intended ingestion/cache path. Keep credentials local and never paste them into chat or commit them. |
| Historical candle ingestion | On 2026-11-06, the user ran `scripts/kite_read_only_ingest.py` successfully against Kite for RELIANCE, 2026-11-02 through 2026-11-04. Output confirmed 3 validated candles, 1 Parquet snapshot, 3 rows read back, exact validated-frame/read-back match (`YES`), and `Order endpoints called: 0`. The user also supplied the checkpoint JSON, instrument snapshot CSV, and Parquet artifact. | No remaining operational blocker for this single-symbol persistence smoke test. Broader universe-scale ingestion/performance validation remains part of later strategy rollout, not Stage 3's live smoke-test acceptance. |
| Corporate events / earnings | Normalized CSV ingestion, independent-source checks, point-in-time visibility, coverage fail-closed behavior, and entry gates are covered by tests. | No complete operator-reviewed event archive has been reconciled across the full 501-symbol universe and required date range. Do not mark event coverage complete or enable entry decisions based on an empty event file. |
| CI | Latest verified CI result before this operational test was green. | Recheck CI on the documentation update and final Stage 3 head. |

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

## Importing an official NSE announcements CSV export

Download the equity announcements CSV from the NSE [Corporate Filings — Announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements) page using the selected date range. Keep the original download unchanged under the Git-ignored `data/corporate_events/raw/` directory. Then normalize it against the archived universe:

```cmd
python scripts/import_nse_announcement_export.py --input data/corporate_events/raw/nse-announcements.csv --universe data/universe/source/nse-nifty500-captured-2026-11-05.csv --output data/corporate_events/nse-announcements-review.csv --excluded-output data/corporate_events/nse-announcements-excluded.csv
```

The adapter supports the NSE export columns `SYMBOL`, `COMPANY NAME`, `SUBJECT`, `DETAILS`, `BROADCAST DATE/TIME`, and optional `ATTACHMENT`, `XBRL`, and submission type. It filters rows to the selected universe, retains excluded/blank-symbol rows in a separate audit file, deduplicates identical records, and retains the broadcast timestamp exactly as supplied. It also adds `review_priority` (`high` or `medium`) and `priority_reason` using conservative subject/detail keyword rules. Unclassified subjects remain `medium` for manual triage rather than being silently deprioritized. A dash-only NSE symbol placeholder is treated as blank and retained in the exclusion audit.

The priority labels are only a suggested review order: high-priority matches include results, board outcomes, capital actions, transactions, management changes, and credit/distress disclosures; investor communications and general updates are medium. This is a keyword heuristic, not a materiality decision. It never fills `event_type` or `event_date`, verifies a filing, or marks coverage complete. Reviewers must still inspect the underlying filing and corroborate it independently. Keep the original 4,329-row export and outputs unchanged as an audit snapshot; rerun the adapter with new output filenames to generate a newly prioritized snapshot.

**Important:** broadcast timestamp is not the underlying event date. The adapter intentionally leaves `event_type`, `event_date`, and per-announcement URL blank for review; the listing page URL is provenance for the export, not a fabricated direct filing URL. Reviewers must inspect the actual filing/attachment and add independent corroboration before translating a candidate into the verified event schema. This export alone cannot establish complete negative coverage for a symbol or date range.

## Candidate intake and review queue (unverified staging)

The first automated preparation step is available as `scripts/prepare_corporate_event_review.py`. It accepts one or more **operator-acquired** announcement CSV exports with these columns:

```csv
symbol,event_type,event_date,announced_at,title,source_url
```

Use the existing `EventType` values (`earnings`, `ordinary_dividend`, `material_corporate_action`, `critical_corporate_action`), ISO dates, and timezone-aware ISO announcement timestamps. The source URL must point to the actual announcement; do not insert invented or generic URLs.

```cmd
python scripts/prepare_corporate_event_review.py --universe data/universe/source/nse-nifty500-captured-2026-11-05.csv --input data/corporate_events/announcements-acquired.csv --output data/corporate_events/event-review-queue.csv
```

This script validates candidate fields, checks universe membership, deduplicates identical rows, and produces stable candidate IDs with `review_status=pending`. It does **not** fetch announcements, independently corroborate events, mark them verified, fill coverage, or create an importable reviewed snapshot. The next increment is a source-specific official-feed adapter and evidence reconciliation. Until then, all 501 coverage rows remain incomplete and entries remain blocked. Preserve operator-acquired raw exports locally under the Git-ignored `data/` directory.

## Measuring the NSE announcement review backlog

After generating the NSE review inbox, run the summary utility against the same archived universe:

```cmd
python scripts/summarize_corporate_event_review.py --universe data/universe/source/nse-nifty500-captured-2026-11-05.csv --input data/corporate_events/nse-announcements-review.csv
```

The report shows total candidates, unique symbols represented, high/medium review counts, review-status counts, per-symbol candidate counts, and symbols with no candidates in this particular export. It rejects candidate rows outside the selected universe and invalid priority labels.

**A symbol absent from the export is not a clean bill of health.** It may have had no announcements in the selected export window, an export/filtering issue, or no matching symbol. The summary deliberately does not infer event absence, coverage completeness, or permission to trade. Keep coverage incomplete until the required date range is reconciled against independent sources.

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
- [x] The dedicated read-only Kite smoke test succeeds: profile authentication, 10,281 normalized NSE cash-equity instruments, 3 RELIANCE daily candles for 2026-11-02 through 2026-11-04, and zero order endpoints called.
- [x] Run `scripts/kite_read_only_ingest.py` against Kite and verify Parquet read-back: 3 validated RELIANCE candles, 1 Parquet snapshot, 3 rows read back, exact match, and zero order endpoints called.
- [ ] Corporate-event coverage has been reconciled for the universe and date range required by the backtest/strategy, with independently verified sources.
- [ ] CI is green on the final Stage 3 head.

Until those criteria are met, Stage 4 remains gated. The Stage 3 PR stays draft and unmerged; `master` remains untouched.
