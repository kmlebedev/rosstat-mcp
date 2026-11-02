# rosstat-mcp

Плагин для Claude Code, Codex, Cursor, Kimi Code, Qwen Code и DeepSeek Harness, который подключает агента к read-only MCP-серверу данных проекта [clickhouse-import-rosstat](https://github.com/kmlebedev/clickhouse-import-rosstat).

Плагин даёт **только MCP**: сервер `rosstat-staging` по адресу `https://mcp.selfinvesting.ru:8443/mcp`. Через него агент читает витрины `v_*` staging-ClickHouse — каталог рядов `v_series_catalog`, макро- и финансовые ряды Росстата, ЦБ, Минфина, MOEX и point-in-time слой (`v_point_in_time`, `v_point_in_time_asof`). Доступ только на чтение витрин: сырые таблицы, DDL и запись сервер отклоняет.

Вместе с MCP плагин ставит один скил — `rosstat-sql`: как найти ряд в `v_series_catalog`, как писать дешёвые и корректные запросы ClickHouse к витринам (последнее значение, г/г по цепным индексам, агрегаты по месяцам, срез `v_point_in_time_asof`) и какие ловушки есть в данных. Агент подхватывает скил сам, когда пишет SQL к `rosstat-staging`; явно — `/rosstat-mcp:rosstat-sql` в Claude Code и Qwen Code, по имени `rosstat-sql` в остальных клиентах. Скил написан по-английски ради экономии токенов, отвечает агент по-русски. Агентов, команд и хуков в плагине нет.

## Доступ

Доступ выдаёт владелец: он добавляет Google-адрес в allowlist `ROSSTAT_MCP_ALLOWED_GOOGLE_EMAILS` на сервере. Токен не нужен и не принимается: сервер авторизует через Google OAuth, а аккаунт не из allowlist получает отказ. В манифестах нет ни токена, ни `headers` — только URL и (для Kimi Code) `auth: "oauth"`.

При первом подключении клиент открывает браузер и просит войти Google-аккаунтом. Kimi Code 2.2.0+: команда `/mcp` или `/mcp-config login <server>`, если браузер не открылся сам. Claude Code и Cursor поддерживают OAuth для remote MCP; Codex и Qwen Code — только в версиях клиента с OAuth (`codex mcp login ...` или аналог). Если клиент не умеет OAuth, он получит `401` и не подключится.

Исключение — DeepSeek Harness: его встроенный MCP-клиент (DSH 0.2.x) не поддерживает MCP OAuth. Поэтому DSH-bundle передаёт токен `ROSSTAT_MCP_TOKEN` в заголовке `Authorization` — так же, как это делали манифесты 0.4.x. Это переходный режим: он работает, пока staging принимает статический bearer-токен; после OAuth-cutover строку MCP в bundle нужно перевести на OAuth (см. раздел [DeepSeek Harness](#deepseek-harness)).

Версии плагина 0.4.x для Claude Code, Codex, Cursor, Kimi Code и Qwen Code с `ROSSTAT_MCP_TOKEN` больше не работают: сервер переведён на OAuth (cutover на `:8443`). Нужна версия 0.5.0+.

## Установка

| Клиент | Команды |
|---|---|
| Claude Code | `claude plugin marketplace add kmlebedev/rosstat-mcp`<br>`claude plugin install rosstat-mcp@rosstat-mcp` |
| Codex | `codex plugin marketplace add kmlebedev/rosstat-mcp`<br>`codex plugin add rosstat-mcp@rosstat-mcp` |
| Kimi Code | `/plugins install https://github.com/kmlebedev/rosstat-mcp` |
| Qwen Code | `qwen extensions install kmlebedev/rosstat-mcp` |
| Cursor | `/add-plugin https://github.com/kmlebedev/rosstat-mcp` |
| DeepSeek Harness | В Plugins установить bundle `github:kmlebedev/rosstat-mcp` (или `plugin_manager` → `install_bundle`) |

После установки — новая сессия или `/reload`.

## Проверка

```bash
claude mcp list
```

До входа ожидается `Needs authentication` или `401`; после Google-входа — `Connected`. В Kimi Code: `/mcp`, вход Google, затем запрос `run_query` (например, `max(date)` из `v_cbr_macro`). Если сервер отвечает `401` после входа — проверьте, что email добавлен в `ROSSTAT_MCP_ALLOWED_GOOGLE_EMAILS`, и перезапустите сессию.

В DeepSeek Harness после установки в Plugins появляются две строки — MCP `rosstat-staging` и `Rosstat MCP` (host half bundle); агент получает инструменты `mcp__rosstat-staging__*` и скил `rosstat-sql`. Если строка MCP не активировалась, проверьте `ROSSTAT_MCP_TOKEN` и перезапустите DSH.

## DeepSeek Harness

DSH ставит плагин как bundle: корневой `package.json` объявляет `dsh.bundle.patch`, а `cordis.patch.yml` добавляет две строки — MCP-подключение `rosstat-staging` и host-плагин `index.js`, который регистрирует скил `rosstat-sql` в реестре скилов DSH. Установка — в Web GUI (Plugins) или инструментом агента:

```text
plugin_manager install_bundle target: github:kmlebedev/rosstat-mcp
```

Так как DSH 0.2.x не умеет MCP OAuth, токен нужен до установки: задайте `ROSSTAT_MCP_TOKEN` в окружении процесса DSH или в `~/.dsh/.env` и перезапустите DSH.

```bash
export ROSSTAT_MCP_TOKEN=<токен>
```

Loader подставляет значение в заголовок `Authorization` выражением `!!js`; в манифесте токена нет. Без токена строка MCP не активируется (`failOnStartupError: true`), но скил остаётся доступен. После установки попросите агента прочитать ряд через `mcp__rosstat-staging__run_query` или загрузить скил `rosstat-sql`.

Ограничение: это переходное решение. Когда staging переключится на Google OAuth, а DSH получит поддержку MCP OAuth, блок `headers` из `cordis.patch.yml` убирается; если DSH OAuth так и не получит, рабочий обход — stdio-мост `npx -y mcp-remote@0.16.0 <url>`. Оба варианта меняются только в `cordis.patch.yml`.

## Разработка

Контракт манифестов (имена, версии, описания, MCP-сервер, отсутствие секретов и токенов, состав репозитория), DSH-bundle (`package.json`, `cordis.patch.yml`, host half, локали и иконка) и скила (один скил, `description` ≤ 300 символов, `SKILL.md` ≤ 6 КБ и весь скил с `references/` ≤ 10 КБ, в SQL-примерах только `v_*` и `system.*`) проверяет `tests/test_manifests.py`:

```bash
python3 -m unittest discover -s tests -v
```

Структурную проверку YAML-патча DSH тест выполняет при установленном PyYAML; CI ставит его отдельным шагом. Тот же набор гоняет CI на каждый push и PR. SQL-примеры скила перед мержем прогоняются на staging через MCP: пример, который не выполнился, в скил не попадает. Новый файл в репозитории нужно добавить в allowlist теста: всё содержимое репозитория уезжает к пользователю при установке.

## Лицензия

MIT — см. [LICENSE](LICENSE).
