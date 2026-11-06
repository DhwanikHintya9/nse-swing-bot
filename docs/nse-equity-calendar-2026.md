# NSE equity trading calendar — 2026

## Source and coverage

- Segment: NSE Capital Market / equities
- Coverage: 2026-01-01 through 2026-12-31
- Holiday source: NSE India, [Market Timings & Holidays](https://www.nseindia.com/resources/exchange-communication-holidays?apiversion=v2)
- Retrieved/verified: 2026-11-05
- Archived input: `data/market_calendar/nse-equity-holidays-2026.csv`
- The CSV contains the 16 weekday equity holidays displayed by NSE when checked on 2026-11-05. Weekend dates are not duplicated in the weekday holiday file.

## Special session

Sunday 2026-11-08 is a special Muhurat trading session, not an ordinary weekday session. It must be explicitly added to the calendar through the `special_sessions` argument.

- Official circular: NSE/CMTR/76941, dated 2026-10-19, "Muhurat Trading session on account of Diwali".
- Pre-open: 14:05–14:20 IST.
- Continuous trading: 14:20–15:40 IST.
- Trade modification: 14:20–15:50 IST.
- Source reference: National Stock Exchange of India Limited, Capital Market Segment.

The calendar's session generator only needs the special session date and its source reference. Session timings are retained here as operational metadata; they are not inferred from a normal weekday schedule.

## Operational notes

- This is an archived 2026 calendar, not an evergreen calendar provider.
- The 2026-01-15 Maharashtra municipal election holiday is included because it appears in NSE's current equity holiday list.
- Recheck official NSE holiday/circular updates before extending coverage or running future dates.
- Do not infer holidays from weekends alone, and do not assume every weekend special session is an ordinary trading day.
