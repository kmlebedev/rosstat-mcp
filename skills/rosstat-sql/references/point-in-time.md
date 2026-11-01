# Point-in-time (vintages)

Official statistics get revised. A model or article dated X should use only what was published before X, and the current value of a past period may differ from what people saw at the time. Use these views for "what was known on date X", "how was it revised", or backtests without look-ahead.

- `v_point_in_time`: every published version of each point. Columns: `source`, `series`, `period_date`, `value`, `published_at`, `vintage`, `vintage_label`. It holds the column comments.
- `v_point_in_time_asof(as_of='YYYY-MM-DD')`: the latest version of each point published **strictly before** `as_of` (`published_at < as_of`). A value published on the `as_of` date itself is excluded. This is a parameterized view, so `DESCRIBE` without the argument fails and its columns are those above.
- `v_point_in_time_version`: the dataset version.

Coverage today is the CBR bulletin "О чём говорят тренды" (`source = 'cbr_dip_bulletin'`). To see which series exist, run `SELECT DISTINCT source, series FROM v_point_in_time`.

## Value as known on a date

```sql
SELECT value, vintage, vintage_label, published_at
FROM v_point_in_time_asof(as_of='2024-02-07')
WHERE source = 'cbr_dip_bulletin' AND series = 'unemployment_sa' AND period_date = '2023-11-30'
```

## Revision history of one point

```sql
SELECT vintage_label, published_at, value
FROM v_point_in_time
WHERE source = 'cbr_dip_bulletin' AND series = 'unemployment_sa' AND period_date = '2023-11-30'
ORDER BY published_at
```
