---
name: rosstat-sql
description: Use whenever answering with data from the rosstat-staging MCP (Rosstat, CBR, MOEX, Minfin ClickHouse marts v_*) - inflation, CPI, key rate, FX, unemployment, GDP, latest values, y/y, as-of vintages. How to find series and write correct, cheap queries.
---

# Answering with Rosstat/CBR data

**Answer the user in Russian**, whatever language this skill is in. Quote series names, `title` and `description` verbatim: users recognise the official wording, and paraphrase hides which series you used.

## Workflow

1. **Find the series** in `v_series_catalog` with one query that covers every concept in the question at once. Each extra round trip costs a turn, and the catalog is small (~9k rows), so a broad search is cheap. Return `unit` and `frequency` with the result to avoid a second lookup:
   ```sql
   SELECT source, series, title, unit, frequency
   FROM v_series_catalog
   WHERE multiSearchAnyCaseInsensitiveUTF8(title, ['ключев', 'курс доллар'])
   LIMIT 50
   ```
   Use Russian stems. Series codes are often long Russian strings, so copy them exactly. If a template already names the series, still read its row here for the unit.
2. **Read the meaning** from `description` and `unit`, not from the code. Similar names differ in coverage and units: a monthly bank rate stored as a share (`0.187`) next to a weekly market rate in percent (`18.76`), individuals vs. companies, federal vs. consolidated budget. A wrong pick gives a confident wrong number. When two sources answer the question, say which you used and why, and convert units before comparing.
3. **Find the view** by the catalog `source`, in one query: view SQL writes each source as a literal, and view names do not follow source names (`domrf_mortgage` is in `v_bank_macro`, `domrf_mortgage_weekly` in `v_domrf_mortgage`). Guessing from comments costs many turns.
   ```sql
   SELECT name, arrayFilter(s -> position(create_table_query, concat('''', s, '''')) > 0, ['domrf_mortgage', 'domrf_mortgage_weekly']) AS sources
   FROM system.tables
   WHERE database = 'default' AND name LIKE 'v\\_%' AND notEmpty(sources)
   ```
   Then read its columns (`system.columns`, with comments) before writing the query. Read a long `description` in one query, not in slices.
4. **Query**, following the rules below. Ready queries: [references/templates.md](references/templates.md).
5. **Answer** with the value, its period date, the unit, and the series used. Say how fresh it is (`max(date)`), and mention gaps or revisions you saw.

For "what was known on date X", backtests, forecasts dated in the past, or "how was it revised", read [references/point-in-time.md](references/point-in-time.md) first. Today's views hold revised values, so using them for a past date leaks the future.

## Access

Only views `v_*` in `default` plus `system.tables` / `system.columns` are readable. A raw table returns `ACCESS_DENIED` (497): that is the permission boundary, so switch to the matching `v_*` instead of retrying. The user is `readonly = 2`: no DDL or writes, session settings allowed.

## Query rules

- **Do the work in ClickHouse.** Aggregate, join and compute there and return the answer, not raw rows: views have up to hundreds of thousands of rows and every row costs context.
- **Filter on raw columns** (`series = …`, `date >= …`). A function over the filtered column hides it from the primary key and turns a lookup into a full scan.
- **Latest value:** `max(date)` with `argMax(value, date)` grouped by series. Use `LIMIT` only for exploration and top-N, never to cut a time series.
- **Windows count rows, not months.** A `ROWS BETWEEN 11 PRECEDING` frame spans 13+ months when a month is missing, so check the frame really covers 12 consecutive months, and add `PARTITION BY series` whenever more than one series is in play.
- **Buckets:** `toStartOfMonth`, `toMonday` (bare `toStartOfWeek` starts on Sunday), or `toStartOfInterval(d, INTERVAL 1 MONTH)`. Second-based intervals align to UTC, not calendar days.
- **Missing row ≠ zero.** Use `WITH FILL` only when absence really means zero, with `STEP toIntervalMonth(1)` for monthly `Date` buckets.
- **Time zone:** the server is not in Moscow. Most marts use `Date`, which has no zone. For `DateTime`, pass `'Europe/Moscow'` to functions and write literals as `toDateTime('…', 'Europe/Moscow')`.
- **Heavy queries:** run `EXPLAIN ESTIMATE <query>` first, and add `SETTINGS max_execution_time = 30`.
- **Russian text:** use `substringUTF8` / `lengthUTF8`. The byte versions cut letters in half.

## Data traps

- **Freshness:** run `max(date)` now. The marts update daily, so a value from memory or an earlier answer may already be stale.
- **Period vs. publication:** `date` is the period the value describes, not when it was published. Rosstat monthly points sit on the month end. Some sources date a quarter by the first day of the next quarter, so read the column comment before naming a quarter.
- **Chain indices:** monthly CPI indices (100 = no change vs. the previous month) compound, so y/y is the product of 12 indices, not their sum.
- **Duplicates:** before aggregating, compare `count()` with `uniqExact(<key>)`. If they differ, take `argMax(value, <version column>)` per key or report the conflict, never an arbitrary row.
- **Precision:** some values are Float32, so `round()` them in the output.
