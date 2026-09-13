# Stage 1 — Ingestion Pipeline: Claude Code Handoff

## Goal
Load all hospitals in `data/hospitals.json` into Tiger Data/Postgres using
the schema already stubbed in `app/services/db_service.py`, so
`search_hospitals()` and `get_prices()` return real data.

## What's already in the repo
- `data/hospitals.json` — 11 hospitals (10 primary + 1 backup), each with
  `mrf_url` and `mrf_format` (`csv`, `json`, or `zip`).
- `app/services/db_service.py` — target schema:
  ```
  hospital_prices(
      hospital_id, hospital_name, code, description,
      gross_charge, cash_price, negotiated_min, negotiated_max
  )
  ```
- `.env.example` — `DATABASE_URL` goes here once Tiger Data is provisioned.

## Confirmed file formats (verified by hand, not assumed)

Every file starts with a 3-row metadata preamble regardless of layout:
row 1 = hospital info headers, row 2 = hospital info values, row 3 = the
real pricing table header. Rows 4+ are data.

**CSV "tall" layout** (confirmed: Texas Children's Hospital) — has a
`payer_name` / `plan_name` column; one row per code+payer combination;
price sits in a single `standard_charge|negotiated_dollar` column.
Real header sample:
```
description,code|1,code|1|type,...,billing_class,setting,...,
standard_charge|gross,standard_charge|discounted_cash,payer_name,
plan_name,...,standard_charge|negotiated_dollar,...,
standard_charge|min,standard_charge|max,standard_charge|methodology,...
```

**CSV "wide" layout** (confirmed: Harris Health – Ben Taub) — NO
`payer_name` column; instead every payer+plan combo gets its own set of
columns baked into the header, e.g.
`standard_charge|Aetna |Commercial PPO|negotiated_dollar`,
`standard_charge|Molina|Medicaid|negotiated_dollar`, etc. One row per
code; most payer columns are empty except whichever apply to that row.
Both `standard_charge|min` and `standard_charge|max` columns exist here
too (already aggregated across payers by the hospital).

Both layouts are valid under the CMS standard (v3.0.0 confirmed on both
files) — hospitals pick tall or wide depending on their vendor. **The
parser must detect which layout a file uses (check for a `payer_name`
column) and normalize both into the same output schema.**

**Normalization rule for `negotiated_min` / `negotiated_max`:**
- Tall layout: `standard_charge|min` / `standard_charge|max` columns are
  already provided directly — use them.
- Wide layout: same — `standard_charge|min` / `standard_charge|max`
  columns exist directly in the header too. Don't recompute by hand across
  the exploded payer columns; the hospital already did that math.

**JSON format** — used by Baylor St. Luke's Main, St. Luke's Woodlands,
St. Luke's Vintage, St. Luke's Sugar Land. **Not yet inspected — do not
assume a structure.** Fetch one real file first (e.g. Baylor St. Luke's)
and look at actual keys before writing the JSON parser. CMS has an
official JSON schema for this, but confirm against the live file rather
than guessing from spec memory, same as we did for the CSV files.

**ZIP format** — Texas Children's and Harris Health URLs point to `.zip`
files; already confirmed both unzip to a single CSV each (tall and wide
respectively, per above). The downloader needs to unzip in-memory/temp
before handing off to the CSV parser.

**Not yet inspected in detail** (assume CSV tall or wide, detect at
runtime, don't hardcode which): Houston Methodist (TMC + Baytown),
Memorial Hermann (Memorial City + Southwest), MD Anderson.

## Tasks, in order
1. **Downloader**: given a `hospitals.json` entry, fetch `mrf_url`; if
   `mrf_format == "zip"`, extract to the contained CSV first.
2. **CSV parser**: skip 2-row metadata preamble, read real header (row 3),
   detect tall vs. wide by presence of `payer_name` column, normalize both
   into the `hospital_prices` schema above.
3. **JSON parser**: inspect Baylor St. Luke's file structure first, then
   write a parser matching what's actually there.
4. **Insert** normalized rows into Postgres via Tiger Data, keyed by
   `hospital_id` from `hospitals.json`.
5. **Sanity check**: query one hospital + one procedure code end-to-end
   and confirm `get_prices()` returns a real row, not an empty list.

## Note on `description` field
The `description` column in these files is each hospital's own free-text
item description (e.g. "GRAFT CV W10XL15CM...") — not the official AMA
CPT descriptor text — so it's fine to store and display as-is. Just don't
separately scrape/store official AMA CPT code descriptions verbatim
elsewhere in the app (AMA holds copyright on those specifically).
