# Stage 4D-5-1 — Operator preflight checklist

Do not start a bulk historical download from this checklist. This is the five-symbol pilot gate only.

## Before running

- [ ] Confirm the active branch is `feature/stage-4b1-evidence-contracts` and PR #2 remains draft.
- [ ] Confirm local `.env` contains `KITE_API_KEY` and `KITE_ACCESS_TOKEN`; never paste either value into chat, logs, screenshots, or the repository.
- [ ] Use the archived universe source `data/universe/source/nse-nifty500-captured-2026-11-05.csv`, effective 2026-09-30. Its source CSV is not a current membership list and must not be relabelled with another effective date.
- [ ] Keep the default five-symbol pilot unless there is a documented reason to change it: RELIANCE, HDFCBANK, INFY, SUNPHARMA, LT. All must remain EQ series and resolve to one current NSE/EQ Kite instrument row.
- [ ] Use `data/market_calendar/nse-equity-holidays-2025-2026.csv`, sourced from NSE's official 2025 Capital Market Segment circular and 2026 equity holiday page. Its coverage supports the default 2025-11-06 to 2026-11-05 pilot window.
- [ ] Include every special trading session that falls inside the requested window. The default CLI explicitly adds the NSE Budget live-trading session on Sunday 2026-02-01 using circular NSE/CMTR/72349. The default window excludes the 2025-10-21 and 2026-11-08 Muhurat sessions; if a changed window includes either, add it back with `--special-session DATE=SOURCE`.
- [ ] Choose a completed-session end date. The requested interval must be wholly inside the calendar's declared coverage.
- [ ] Confirm the output directory is local and Git-ignored (`data/market_data` by default).

## Run

The defaults use the approved five symbols, the combined official holiday file, and the explicitly sourced 2026-02-01 Sunday special session for the rolling 12-month window:

```bash
python scripts/kite_read_only_pilot.py
```

To change the dates or calendar, supply explicit arguments and ensure the source coverage supports the entire requested interval.

## After running

- [ ] Confirm the command reports `Read-only mode: YES` and `Order endpoints called: 0`.
- [ ] Preserve the generated immutable manifest and all referenced Parquet/quarantine artifacts together.
- [ ] Verify the manifest SHA-256 using the project manifest verifier before sharing the evidence.
- [ ] Review every symbol's mapping, first/last candle, row count, missing sessions, unexpected dates, chunk completion, request/retry counters, snapshot hashes, and Parquet read-back status.
- [ ] Treat any nonzero exit code or `failed_or_incomplete` status as a failed pilot. Do not fill gaps or mark it accepted manually.
- [ ] Share only the non-secret manifest/report and sanitized errors. Never share `.env`, access tokens, API keys, request headers, or authenticated URLs.

## What a pass does not authorize

A successful five-symbol pilot validates only the acquisition mechanics and the requested date window for those five symbols. It does not prove five-year retention, historical constituent membership, full corporate-action adjustment, complete event coverage, or strategy profitability. Historical-depth probing and 500-symbol ingestion require a separate review and explicit gate. No performance evaluation or live trading is authorized by this pilot.
