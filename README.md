# rosstat-mcp

Плагин для Claude Code, Codex, Cursor, Kimi Code и Qwen Code, который подключает агента к read-only MCP-серверу данных проекта [clickhouse-import-rosstat](https://github.com/kmlebedev/clickhouse-import-rosstat).

Плагин даёт **только MCP**: сервер `rosstat-staging` по адресу `https://mcp.selfinvesting.ru:8443/mcp`. Через него агент читает витрины `v_*` staging-ClickHouse — каталог рядов `v_series_catalog`, макро- и финансовые ряды Росстата, ЦБ, Минфина, MOEX и point-in-time слой (`v_point_in_time`, `v_point_in_time_asof`). Доступ только на чтение витрин: сырые таблицы, DDL и запись сервер отклоняет. Скилов, агентов и команд в плагине нет.

## Токен

Токен выдаёт владелец репозитория. Положите его в переменную окружения `ROSSTAT_MCP_TOKEN` до запуска клиента:

```bash
export ROSSTAT_MCP_TOKEN=<токен>
```

В Cursor токен задаётся переменной плагина `ROSSTAT_MCP_TOKEN` (Plugins → Configure). В манифестах токена нет — только ссылка на переменную.

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

Ожидается строка `plugin:rosstat-mcp:rosstat-staging: https://mcp.selfinvesting.ru:8443/mcp (HTTP) - ✔ Connected`. Без токена или с неверным токеном сервер отвечает 401.

## Миграция с плагина `clickhouse-import-rosstat`

До версии 0.3.0 плагин публиковался из корня репозитория `clickhouse-import-rosstat` вместе с ролевыми скилами, и установка скачивала весь проект (~200 МБ). Тот маркетплейс больше не обновляется. Удалите старую установку и поставьте `rosstat-mcp` по таблице выше:

| Клиент | Удаление |
|---|---|
| Claude Code | `claude plugin marketplace remove clickhouse-import-rosstat` |
| Codex | `codex plugin marketplace remove clickhouse-import-rosstat` |
| Kimi Code | `/plugins remove clickhouse-import-rosstat` |
| Qwen Code | `qwen extensions uninstall clickhouse-import-rosstat` |
| Cursor | удалить плагин `clickhouse-import-rosstat` в настройках плагинов |

## Разработка

Контракт манифестов (имена, версии, описания, MCP-сервер, отсутствие секретов, состав репозитория) проверяет `tests/test_manifests.py`:

```bash
python3 -m unittest discover -s tests -v
```

Тот же набор гоняет CI на каждый push и PR. Новый файл в репозитории нужно добавить в allowlist теста: всё содержимое репозитория уезжает к пользователю при установке.

## Лицензия

MIT — см. [LICENSE](LICENSE).
