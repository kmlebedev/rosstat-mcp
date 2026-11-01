---
name: rosstat-sql
description: Use for any SQL via the rosstat-staging MCP (Rosstat/CBR/MOEX ClickHouse marts v_*) - find a series, latest value, dynamics, y/y, what was known as of a date. Rules for cheap, correct ClickHouse queries and data traps.
---

# Querying Rosstat/CBR marts

1. **Answer the user in Russian.** Quote series names, `title`, `description` verbatim.

## Access
- Only views `v_*` in `default` plus `system.tables`/`system.columns` are readable. Raw tables return `ACCESS_DENIED` (497): a permission boundary, not a query bug; use the matching `v_*`.
- User is `readonly = 2`: no DDL/INSERT; session settings allowed.
- Server time zone is not Moscow. Most marts use `Date` (no zone issue); for `DateTime` columns pass `'Europe/Moscow'` to functions and write literals as `toDateTime('…', 'Europe/Moscow')`.

## Find data
1. Series: `v_series_catalog` (`source`, `series`, `title`, `unit`, `frequency`, `description`). Meaning and units come from `description`/`unit`, never from the code. Series codes are often long Russian strings: copy them exactly.
2. View: every `v_*` has a table comment and column comments.
```sql
SELECT name, substringUTF8(comment, 1, 160) AS about
FROM system.tables
WHERE database = 'default' AND name LIKE 'v\\_%' AND (name ILIKE '%rosstat%' OR comment ILIKE '%ИПЦ%')
```
3. Columns: `SELECT name, type, comment FROM system.columns WHERE database = 'default' AND table = '<view>'`.

## Query rules
- Filter on raw columns in `WHERE` (`series = …`, `date >= …`); no functions over the filtered column.
- Aggregate in ClickHouse; return the answer, not raw rows. `LIMIT` only for exploration and top-N, never to cut a time series.
- Latest value: `max(date)` + `argMax(value, date)` grouped by series; not `ORDER BY date DESC LIMIT 1` over a whole view.
- Buckets: `toStartOfMonth`, `toMonday` (not bare `toStartOfWeek`: Sunday), `toStartOfInterval(d, INTERVAL 1 MONTH)`; never second-based intervals for days (they align to UTC).
- Missing row ≠ zero: `WITH FILL` only when absence truly means zero; on `Date` add `STEP toIntervalMonth(1)` for months.
- Window/y-o-y calculations run over the full series, then filter the output period. `ROWS` frames count rows, not months: prove the frame is 12 consecutive months.
- Before a heavy query run `EXPLAIN ESTIMATE <query>`; add `SETTINGS max_execution_time = 30`.

## Data traps
- Duplicates: before aggregating compare `count()` with `uniqExact(<key>)`; if they differ, take `argMax(value, <version column>)` per key or report the conflict; never pick an arbitrary row.
- Dates: Rosstat monthly points sit on month-end; quarterly points of some sources sit on the 1st day of the quarter after the reported one. Read the column comment.
- Period date ≠ publication date. Freshness = `max(date)` queried now, never from memory.
- Text: use `substringUTF8`/`lengthUTF8` on Russian strings. Some values are Float32: `round()` them in output.
- Units differ across sources (percent vs share, million vs billion, index 100 = no change). Check `unit` before comparing.
- Monthly CPI indices (100 = no change vs previous month) chain: y/y = product of 12 indices, not a sum.

## Point-in-time (vintages)
- `v_point_in_time`: every published version (`source`, `series`, `period_date`, `value`, `published_at`, `vintage`, `vintage_label`).
- `v_point_in_time_asof(as_of='YYYY-MM-DD')`: what was known strictly before the date (`published_at < as_of`). Parameterized view: `DESCRIBE` without the argument fails; columns as above.
- `v_point_in_time_version`: dataset version.

## Templates
Latest value and freshness:
```sql
SELECT series, max(date) AS last_date, argMax(value, date) AS last_value, count() AS points
FROM v_rosstat_macro
WHERE series = 'Индексы потребительских цен на услуги по Российской Федерации'
GROUP BY series
```
Y/y from a monthly chain index:
```sql
SELECT * FROM (
  SELECT series, date, value AS mom_index,
    round((exp(sum(log(value / 100)) OVER w) - 1) * 100, 2) AS yoy_pct,
    count() OVER w AS n, min(date) OVER w AS w_start
  FROM v_rosstat_macro
  WHERE series = 'Индексы потребительских цен на услуги по Российской Федерации'
  WINDOW w AS (PARTITION BY series ORDER BY date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
)
WHERE n = 12 AND dateDiff('month', w_start, date) = 11 AND date >= '2025-09-01'
ORDER BY date
```
Monthly average of a daily series:
```sql
SELECT toStartOfMonth(date) AS month, avg(value) AS avg_value, count() AS days
FROM v_cbr_macro
WHERE series = 'cbr_currency_usd' AND date >= '2025-01-01'
GROUP BY month
ORDER BY month
```
As-of revision check:
```sql
SELECT value, vintage, vintage_label, published_at
FROM v_point_in_time_asof(as_of='2024-02-07')
WHERE source = 'cbr_dip_bulletin' AND series = 'unemployment_sa' AND period_date = '2023-11-30'
```
