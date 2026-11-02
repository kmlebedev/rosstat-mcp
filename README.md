# rosstat-mcp

Плагин для Claude Code, Codex, Cursor, Kimi Code и Qwen Code, который подключает агента к read-only MCP-серверу данных проекта [clickhouse-import-rosstat](https://github.com/kmlebedev/clickhouse-import-rosstat).

Плагин даёт **только MCP**: сервер `rosstat-staging` по адресу `https://mcp.selfinvesting.ru:8443/mcp`. Через него агент читает витрины `v_*` staging-ClickHouse — каталог рядов `v_series_catalog`, макро- и финансовые ряды Росстата, ЦБ, Минфина, MOEX и point-in-time слой (`v_point_in_time`, `v_point_in_time_asof`). Доступ только на чтение витрин: сырые таблицы, DDL и запись сервер отклоняет.

Вместе с MCP плагин ставит один скил — `rosstat-sql`: как найти ряд в `v_series_catalog`, как писать дешёвые и корректные запросы ClickHouse к витринам (последнее значение, г/г по цепным индексам, агрегаты по месяцам, срез `v_point_in_time_asof`) и какие ловушки есть в данных. Агент подхватывает скил сам, когда пишет SQL к `rosstat-staging`; явно — `/rosstat-mcp:rosstat-sql` в Claude Code и Qwen Code, по имени `rosstat-sql` в остальных клиентах. Скил написан по-английски ради экономии токенов, отвечает агент по-русски. Агентов, команд и хуков в плагине нет.

## Доступ

Доступ выдаёт владелец: он добавляет Google-адрес в allowlist `ROSSTAT_MCP_ALLOWED_GOOGLE_EMAILS` на сервере. Токен не нужен и не принимается: сервер авторизует через Google OAuth, а аккаунт не из allowlist получает отказ. В манифестах нет ни токена, ни `headers` — только URL и (для Kimi Code) `auth: "oauth"`.

При первом подключении клиент открывает браузер и просит войти Google-аккаунтом. Kimi Code 2.2.0+: команда `/mcp` или `/mcp-config login <server>`, если браузер не открылся сам. Claude Code и Cursor поддерживают OAuth для remote MCP; Codex и Qwen Code — только в версиях клиента с OAuth (`codex mcp login ...` или аналог). Если клиент не умеет OAuth, он получит `401` и не подключится.

Версии плагина 0.4.x с `ROSSTAT_MCP_TOKEN` больше не работают: сервер переведён на OAuth (cutover на `:8443`). Нужна версия 0.5.0+.

## Установка

| Клиент | Команды |
|---|---|
| Claude Code | `claude plugin marketplace add kmlebedev/rosstat-mcp`<br>`claude plugin install rosstat-mcp@rosstat-mcp` |
| Codex | `codex plugin marketplace add kmlebedev/rosstat-mcp`<br>`codex plugin add rosstat-mcp@rosstat-mcp` |
| Kimi Code | `/plugins install https://github.com/kmlebedev/rosstat-mcp` |
| Qwen Code | `qwen extensions install kmlebedev/rosstat-mcp` |
| Cursor | `/add-plugin https://github.com/kmlebedev/rosstat-mcp` |

После установки — новая сессия или `/reload`.

## Проверка

```bash
claude mcp list
```

До входа ожидается `Needs authentication` или `401`; после Google-входа — `Connected`. В Kimi Code: `/mcp`, вход Google, затем запрос `run_query` (например, `max(date)` из `v_cbr_macro`). Если сервер отвечает `401` после входа — проверьте, что email добавлен в `ROSSTAT_MCP_ALLOWED_GOOGLE_EMAILS`, и перезапустите сессию.

## Разработка

Контракт манифестов (имена, версии, описания, MCP-сервер, отсутствие секретов и токенов, состав репозитория) и скила (один скил, `description` ≤ 300 символов, `SKILL.md` ≤ 6 КБ и весь скил с `references/` ≤ 10 КБ, в SQL-примерах только `v_*` и `system.*`) проверяет `tests/test_manifests.py`:

```bash
python3 -m unittest discover -s tests -v
```

Тот же набор гоняет CI на каждый push и PR. SQL-примеры скила перед мержем прогоняются на staging через MCP: пример, который не выполнился, в скил не попадает. Новый файл в репозитории нужно добавить в allowlist теста: всё содержимое репозитория уезжает к пользователю при установке.

## Лицензия

MIT — см. [LICENSE](LICENSE).
