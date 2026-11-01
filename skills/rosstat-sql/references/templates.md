# Query templates

Each template ran on staging. Replace the series code with one copied from `v_series_catalog`.

## Find a view by topic

```sql
SELECT name, substringUTF8(comment, 1, 160) AS about
FROM system.tables
WHERE database = 'default' AND name LIKE 'v\\_%' AND (name ILIKE '%rosstat%' OR comment ILIKE '%ИПЦ%')
```

To list a view's columns, run `SELECT name, type, comment FROM system.columns WHERE database = 'default' AND table = '<view>'`.

## Latest value and freshness

```sql
SELECT series, max(date) AS last_date, round(argMax(value, date), 2) AS last_value, count() AS points
FROM v_rosstat_macro
WHERE series = 'Индексы потребительских цен на услуги по Российской Федерации'
GROUP BY series
```

## Y/y from a monthly chain index

The inner query compounds 12 monthly indices over the full series. The outer filter keeps only frames that cover 12 consecutive months.

```sql
SELECT date, mom_index, yoy_pct
FROM (
  SELECT series, date, round(value, 2) AS mom_index,
    round((exp(sum(log(value / 100)) OVER w) - 1) * 100, 2) AS yoy_pct,
    count() OVER w AS n, min(date) OVER w AS w_start
  FROM v_rosstat_macro
  WHERE series = 'Индексы потребительских цен на услуги по Российской Федерации'
  WINDOW w AS (PARTITION BY series ORDER BY date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
)
WHERE n = 12 AND dateDiff('month', w_start, date) = 11 AND date >= '2025-09-01'
ORDER BY date
```

## Monthly average and month-end value of daily series

```sql
SELECT series, toStartOfMonth(date) AS month,
  round(avg(value), 2) AS avg_value, round(argMax(value, date), 2) AS month_end, count() AS days
FROM v_cbr_macro
WHERE series IN ('cbr_currency_usd', 'cbr_key_rate') AND date >= '2025-01-01'
GROUP BY series, month
ORDER BY series, month
```
