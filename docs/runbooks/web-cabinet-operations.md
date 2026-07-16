---
title: "Эксплуатация web-кабинета Shumeyko"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: draft
source_of_truth: false
updated_at: "2026-07-15"
---

# Эксплуатация web-кабинета Shumeyko

> **Статус draft.** Команды используются как рабочая эксплуатационная база, но
> полный end-to-end прогон всех privileged production-команд в рамках
> документационной синхронизации не выполнялся. Повышать runbook до `active`
> можно только после отдельной безопасной проверки полного сценария.

Production-кабинет `analitika.offonika.ru` работает как read-only продукт.
`shumeiko.offonika.ru` является staff-only test-контуром. HTML-оболочки
открываются публично, но данные отчета, Excel export, AI-чат и live checks
доступны только после входа.

# Runtime Contours

Runtime разделен на два процесса:

- production: `shumeiko-web-prod.service`, `127.0.0.1:8097`,
  `/etc/shumeiko-web-prod.env`, `https://analitika.offonika.ru`;
- test: `shumeiko-web-test.service`, `127.0.0.1:8098`,
  `/etc/shumeiko-web-test.env`, `https://shumeiko.offonika.ru`.

Legacy `shumeiko-web.service` на `8096` сохраняется только на 24-часовое окно
rollback и после cutover не имеет публичного nginx-маршрута.

Оба локальных процесса контролируются отдельными timers:

```bash
systemctl status shumeiko-web-prod-health.timer
systemctl status shumeiko-web-test-health.timer
systemctl start shumeiko-web-prod-health.service
systemctl start shumeiko-web-test-health.service
```

Проверка считается успешной только при `status=ok`, правильном
`runtimeEnvironment` и одинаковых `backendBuildId`/`staticBuildId`.

## Environment files

Production environment задает `SHUMEYKO_RUNTIME_ENVIRONMENT=production`,
`SHUMEYKO_CLIENT_LOGIN_ENABLED=true`, отдельное имя cookie и
`SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED=true`. Test environment задает
`SHUMEYKO_RUNTIME_ENVIRONMENT=test`, `SHUMEYKO_CLIENT_LOGIN_ENABLED=false`,
отдельную test БД/report root/source root и по умолчанию
`SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED=false`.

Если test БД принадлежит отдельной PostgreSQL-роли, перед запуском
`scripts/create_runtime_env_files.py --apply` нужно передать ее полный URL через
одноразовую переменную окружения `SHUMEYKO_TEST_DATABASE_URL`. Скрипт проверит,
что URL ведет в БД из `--test-database`, и не выведет URL или пароль. После
команды переменную нужно удалить из shell environment.

После restore production backup в test БД сначала выполнить dry-run, затем
применение sanitization только через test EnvironmentFile:

```bash
systemd-run --wait --collect --pipe \
  --unit=shumeiko-prepare-test-db \
  --property=WorkingDirectory=/opt/shumeyko-runtime/test/current \
  --property=EnvironmentFile=/etc/shumeiko-web-test.env \
  /opt/shumeyko-runtime/test/current/.venv/bin/python \
  scripts/prepare_test_database.py

systemd-run --wait --collect --pipe \
  --unit=shumeiko-prepare-test-db-apply \
  --property=WorkingDirectory=/opt/shumeyko-runtime/test/current \
  --property=EnvironmentFile=/etc/shumeiko-web-test.env \
  /opt/shumeyko-runtime/test/current/.venv/bin/python \
scripts/prepare_test_database.py --apply
```

До запуска test создать отдельного system user и передать ему только test
каталоги (production report/snapshot/backup каталоги не менять):

```bash
systemd-sysusers deploy/sysusers.d/shumeiko-runtime.conf
chown -R shumeyko-test:shumeyko-test /data/shumeyko/test
find /data/shumeyko/test -type d -exec chmod 0750 {} +
find /data/shumeyko/test -type f -exec chmod 0640 {} +
```

Скрипт отказывается работать вне `runtime_environment=test` или с БД, имя
которой не заканчивается на `_test`. Боевые integration secrets после clone
не сохраняются. Отдельные read-only test-ключи вводятся staff вручную и только
после этого master-switch внешних интеграций может быть включен.
Повторный `--apply` допустим: файлы current reports, уже находящиеся внутри
test report root, должны быть отмечены как `reused`, а не `unavailable`.

## Maintenance communication

До плановых работ задать безопасный `SHUMEYKO_MAINTENANCE_MESSAGE`, перезапустить
production web до начала окна и отправить клиенту сообщение:

> Плановые технические работы в кабинете аналитики: `<дата и время по Москве>`.
> В это время кабинет может быть временно недоступен. После завершения отдельно
> подтвердим восстановление работы.

После smoke-check очистить сообщение и повторно проверить `/api/health`.

Nginx должен проксировать в FastAPI:

- `/`;
- `/cabinet`;
- `/ai`;
- `/integrations`;
- `/static/*`;
- `/api/*`.

Старый статический shell из `/var/www/offonika-shumeiko/shumeiko/index.html`
нельзя использовать для web-кабинета: он хранит устаревший контракт и может
обращаться к `unitRows` из public summary. Актуальный nginx-шаблон лежит в
`deploy/nginx/analitika.offonika.ru.conf` и
`deploy/nginx/shumeiko.offonika.ru.conf`.

# Безопасный запуск backend

`shumeiko-web-prod.service` нельзя включать после аварийной остановки без лимита
памяти и smoke-check. Актуальный шаблон лежит в
`deploy/systemd/shumeiko-web-prod.service` и задает:

- `MemoryMax=2G`;
- один `uvicorn` worker на `127.0.0.1:8097`;
- `Restart=on-failure`;
- `EnvironmentFile=/etc/shumeiko-web-prod.env`.

Установка/обновление unit:

```bash
sudo install -d /etc/systemd/system/postgresql@16-main.service.d
sudo cp deploy/systemd/postgresql-16-main-data.conf \
  /etc/systemd/system/postgresql@16-main.service.d/shumeiko-data.conf
sudo cp deploy/systemd/shumeiko-web-prod.service /etc/systemd/system/
sudo cp deploy/systemd/shumeiko-web-test.service /etc/systemd/system/
sudo systemctl daemon-reload
```

PostgreSQL хранит data directory на `/data`. Drop-in
`postgresql-16-main-data.conf` заставляет cluster ждать mount `/data` при
перезагрузке сервера. Без этой зависимости PostgreSQL может один раз упасть до
монтирования диска, а web-сервис останется в restart-loop до ручного запуска
cluster.

Установка/обновление nginx-маршрута:

```bash
sudo cp deploy/nginx/analitika.offonika.ru.conf /etc/nginx/sites-available/
sudo cp deploy/nginx/shumeiko.offonika.ru.conf /etc/nginx/sites-available/
sudo nginx -t
sudo systemctl reload nginx
```

Перед включением проверить, что summary API не отдает полный `unitRows`, а
PostgreSQL timeout настроен через `SHUMEYKO_POSTGRES_STATEMENT_TIMEOUT_MS`
или default `15000`.

Для крупного отчета отдельно проверить первый и повторный вызовы защищенных
`/api/reports/{id}/summary` и `/api/reports/{id}/freshness`. Первый вызов после
перезапуска должен укладываться в 8 секунд, повторный — в 3 секунды. Сервер пишет
безопасные строки `report_endpoint_timing`; длительность более 5 секунд имеет
уровень warning. `QueryCanceled`, HTTP 500 или постоянное состояние UI
`Загружаем клиента` считаются инцидентом, а не основанием повышать timeout.

Порядок первого запуска:

```bash
sudo systemctl start shumeiko-web-prod.service shumeiko-web-test.service
curl --noproxy '*' -fsS http://127.0.0.1:8097/api/health
curl --noproxy '*' -fsS http://127.0.0.1:8098/api/health
free -h
ps aux --sort=-%mem | head -20
journalctl -u shumeiko-web-prod.service -n 100 --no-pager
journalctl -u shumeiko-web-test.service -n 100 --no-pager
```

После nginx reload проверить, что публичный домен отдает FastAPI shell, а не
legacy static:

```bash
curl --noproxy '*' -fsS https://analitika.offonika.ru/cabinet | grep -q '/static/app.js'
curl --noproxy '*' -fsS https://analitika.offonika.ru/ai | grep -q '/static/app.js'
curl --noproxy '*' -fsS https://analitika.offonika.ru/integrations | grep -q '/static/app.js'
curl --noproxy '*' -fsS https://analitika.offonika.ru/static/app.js | grep -q 'function asArray'
curl --noproxy '*' -fsS https://analitika.offonika.ru/static/app.js | grep -vq 'summary.unitRows'
curl --noproxy '*' -fsS https://analitika.offonika.ru/api/health
curl --noproxy '*' -fsS https://shumeiko.offonika.ru/api/health | grep -q '"runtimeEnvironment":"test"'
```

Открыть кабинет в браузере и повторить проверку памяти. Если после входа и
переключения отчетов Python остается стабильно ниже 1-1.5G, можно включить
автозапуск:

```bash
sudo systemctl enable shumeiko-web-prod.service shumeiko-web-test.service
```

Если память снова растет до лимита или health-check нестабилен, остановить
сервис и оставить его disabled до разбора:

```bash
sudo systemctl stop shumeiko-web-prod.service shumeiko-web-test.service
sudo systemctl disable shumeiko-web-prod.service shumeiko-web-test.service
```

# Доступы

Пользователи создаются только server-side, публичной регистрации нет.

```bash
cd /opt/shumeyko-partners-wb-unit-economics
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/manage_web_users.py list
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/manage_web_users.py create \
  --email client@example.com \
  --name "Client" \
  --role client \
  --password-file /root/shumeiko-web-users.txt
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/manage_web_users.py reset-password \
  --email client@example.com \
  --password-file /root/shumeiko-web-users.txt
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/manage_web_users.py disable \
  --email client@example.com
```

Файл с временными паролями должен быть доступен только root. Пароли не
записываются в Git, Markdown, HTML, JSON или чат.

# Обновление report run

Штатный путь: пересобрать расчетные витрины в БД, экспортировать артефакты и
атомарно опубликовать новый `current` report:

```bash
cd /opt/shumeyko-partners-wb-unit-economics
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/rebuild_report_from_sources.py \
  --tenant-id shumeyko \
  --report-id excel_mvp_YYYY_MM_DD \
  --export-all
```

Если ручная пересборка использует `--source-snapshot-set-id`, она обязана
передать зарегистрированную lineage-связь через `--source-refresh-run-id` либо
через точечную связь источника. Для восстановления истории остатков передаются
точный каталог и run, в котором зарегистрирована именно эта коллекция:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/rebuild_report_from_sources.py \
  --report-id excel_mvp_YYYY_MM_DD \
  --source-snapshot-set-id composite_snapshot_id \
  --wb-stock-history-dir data/source_refresh/<run>/wb_stock_history_daily \
  --stock-history-refresh-run-id source_refresh_<id>
```

Каталог должен совпадать с `raw_path` зарегистрированной коллекции
`wb_stock_history_daily`. Несвязанная текстовая метка snapshot теперь
отклоняется до сохранения report run. Доступное окно истории WB считается от
текущей московской даты; период целиком старше трёх месяцев не отправляется в
WB и фиксируется как непокрытый, без подстановки нулей.

Экспорт без пересборки источников:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/export_report_artifacts.py \
  --report-id excel_mvp_YYYY_MM_DD \
  --excel --docx --pdf --html --csv
```

Legacy recovery path, только если нужно восстановиться из уже принятого Excel:

```bash
cd /opt/shumeyko-partners-wb-unit-economics
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/import_web_report_from_excel.py \
  --workbook reports/shumeyko_wb_excel_mvp.xlsx \
  --report-id excel_mvp_YYYY_MM_DD
```

Если `SHUMEYKO_DATABASE_URL` не задан и `--database-url` не передан, команды
используют локальный fallback `sqlite:///data/web/shumeyko_web.sqlite3`. Это
нормально для локального smoke, но для production может создать “обновили не ту
базу” эффект. Перед production-публикацией всегда использовать тот же runtime
database URL, что и `shumeiko-web-prod.service`; значение не печатать в чат, логи
или документацию.

Идемпотентные schema migrations и backfill запускаются отдельной командой до
restart web. На production безопаснее передать существующий EnvironmentFile
через systemd, не читая и не печатая его содержимое:

```bash
systemd-run --wait --collect --pipe \
  --unit=shumeiko-web-migrate \
  --property=WorkingDirectory=/opt/shumeyko-partners-wb-unit-economics \
  --property=EnvironmentFile=/etc/shumeiko-web-prod.env \
  /opt/shumeyko-partners-wb-unit-economics/.venv/bin/python \
  scripts/migrate_web_database.py
```

Команда выводит только примененную `schema_version`; database URL и секреты
не выводятся.

Для canary до клиентской публикации staff-run можно поставить в очередь через
тот же runtime-контур, не выводя organization ID или учетные данные:

```bash
systemd-run --wait --collect --pipe \
  --unit=shumeiko-accounting-canary-enqueue \
  --property=WorkingDirectory=/opt/shumeyko-partners-wb-unit-economics \
  --property=EnvironmentFile=/etc/shumeiko-web-prod.env \
  /opt/shumeyko-partners-wb-unit-economics/.venv/bin/python \
  scripts/enqueue_accounting_report.py \
  --client-match '<уникальная часть имени клиента>' \
  --reference-organization-file data/.../organizations.raw.json \
  --period-month YYYY-MM --report-kind month_close_control \
  --idempotency-key '<стабильный canary key>'
```

Reference-файл должен находиться в локальном `data/`, содержать ровно одну
организацию и не выводится командой. Вместо него допускается безопасный
уникальный `--company-match`. Скрипт выбирает активного staff-пользователя для
audit и печатает только ID и статус generation run. CLI только ставит canary в
очередь; после получения `generation_run_id` оператор запускает тот же worker
template, который использует web-кнопка:

```bash
systemctl start \
  'shumeiko-source-refresh-worker@<generation_run_id>.service'
```

Повторный запуск unit безопасен: завершенный или уже занятый generation run не
создает новый report run.

Production drop-in worker этого пилота задает
`SHUMEYKO_ACCOUNTING_RECORDTYPE_PAGE_SIZE=50000` только после live GET-пробы
той же публикации. Общий default приложения равен 10000; повышать значение для
другой 1С без отдельной проверки статуса `200` и полного размера страницы
нельзя.

Для ручного ввода идентификаторов поддерживается пара
`--tenant-id ... --client-id ...`, но CLI проверяет их принадлежность друг
другу. Для audit-pack предпочтителен `--client-match`: он атомарно разрешает
оба идентификатора по единственному клиенту и не позволяет случайно запустить
контрольную сверку в общем tenant другого клиента.

После завершения month-close canary проверить payload hash, состав Excel и
сверку со штатной ОСВ безопасным агрегатным валидатором:

```bash
systemd-run --wait --collect --pipe \
  --unit=shumeiko-accounting-canary-verify \
  --property=WorkingDirectory=/opt/shumeyko-partners-wb-unit-economics \
  --property=EnvironmentFile=/etc/shumeiko-web-prod.env \
  /opt/shumeyko-partners-wb-unit-economics/.venv/bin/python \
  scripts/verify_month_close_canary.py \
  --report-id '<report_id>' \
  --reference-workbook reports/.../osv_reconciliation.xlsx \
  --reference-side standard \
  --excel-output reports/canary/month_close_control.xlsx \
  --expected-report-accounts 33 \
  --expected-reference-accounts 40 \
  --expected-common-accounts 31 \
  --expected-exact-accounts 30 \
  --expected-mismatch-accounts 1 \
  --expected-report-only-accounts 2 \
  --expected-reference-only-accounts 9
```

Валидатор не печатает названия организаций, номера счетов или суммы: только
hash/parity и агрегированные количества exact/mismatch/missing. Если
`payload_hash_valid` или `excel_parity` ложны либо бухгалтерская сверка не
соответствует контрольному audit-pack, `accounting_baseline_match=false`,
команда завершается ненулевым кодом и вид включать нельзя. Значения expected
относятся только к зафиксированному audit-pack; после изменения исходных
проводок требуется новая штатная ОСВ и новый baseline, а не подгонка expected.

Или через авторизованный admin API:

```bash
POST /api/admin/reports/import
```

1. Проверить `GET /api/reports`, `GET /api/reports/{id}/freshness`,
   KPI summary и Excel export.
2. Перед отправкой клиенту проверить `readiness` в `summary` или `freshness`:
   `ready` можно отправлять, `needs_review` требует ручной проверки,
   `partial_period`, `partial_source` и `source_coverage_gap` требуют явной
   клиентской оговорки, `failed` нельзя отправлять до устранения
   `blockingReasons`.
3. Открыть `/cabinet`, войти под `consultant/admin` и сверить, что первый экран
   показывает readiness, score, причины, следующий шаг, качество отчета и
   проблемные строки без raw snapshots и технических секретов.
4. Убедиться, что старые публичные artifacts не доступны: `/data/*.json`,
   `/downloads/*.xlsx`, `/.env`.

# Обновление UI shell

UI shell живет в FastAPI assets внутри этого репозитория:

- HTML: `src/wb_unit_economics/web/templates/cabinet.html`;
- JS: `src/wb_unit_economics/web/static/app.js`;
- CSS: `src/wb_unit_economics/web/static/styles.css`.

После изменения клиентской страницы проверить публичный HTML, JS и API:

```bash
curl --noproxy '*' -fsS https://analitika.offonika.ru/ | grep -q '/static/app.js'
curl --noproxy '*' -fsS https://analitika.offonika.ru/static/app.js | grep -q 'function asArray'
curl --noproxy '*' -fsS https://analitika.offonika.ru/api/health
```

Для клиентской вкладки `Упущенные продажи` публичный shell должен показывать
колонки `Остаток 1С` и `Склады 1С`. Данные в этих колонках приходят из
`/api/reports/{id}/summary`, а не из статического HTML.

# AI

Ключ OpenAI задается только в runtime окружении сервиса, например в
`/etc/shumeiko-web-prod.env`.

AI-инструменты работают только поверх расчетной витрины и audit:

- summary;
- SKU search;
- loss drivers;
- data-quality issues;
- period comparison;
- management report draft;
- read-only live checks, если включены.

Если ключ пустой или OpenAI недоступен, кабинет отвечает deterministic fallback
по тем же серверным tool outputs.

Для self-hosted ChatKit custom-server режима нужен
`SHUMEYKO_CHATKIT_ENABLED=true`. Web component подключается к same-origin
`/api/chatkit` через `apiURL` и custom `fetch`; domain key не используется.
До staff acceptance production оставляет feature flag выключенным.
`/api/ai/config` показывает выбранный transport, а `/api/chatkit` при
выключенном флаге возвращает `404`. Откат — вернуть
`SHUMEYKO_CHATKIT_ENABLED=false`; существующие private AI threads и сообщения
остаются доступны штатному SSE UI.

Для test acceptance установить versioned drop-in
`deploy/systemd/shumeiko-web-test.service.d/chatkit.conf`, выполнить
`systemctl daemon-reload` и перезапустить только `shumeiko-web-test.service`.

В UI панель `AI-аналитик` должна явно показывать источник ответа:

- `OpenAI` — ответ собран моделью поверх whitelisted tools;
- `Fallback` — ответ собран локально по расчетной витрине, без обращения к
  модели или после safe error OpenAI.

Для `consultant/admin` fallback виден явно. Для `client` показывается мягкий
статус расчетной витрины без технической причины ошибки.

# Интеграции

Ключи WB/1С хранятся в tenant-level разделе `Интеграции`, а не в профиле
пользователя. Доступен только `consultant/admin`.

Операции:

- добавить или переименовать WB-кабинет клиента;
- сохранить или заменить ключ;
- проверить подключение read-only;
- отключить интеграцию.

Если у клиента два или больше WB-кабинета, консультант добавляет каждый кабинет
отдельной строкой в виджете `Интеграции` и привязывает его к нужной организации
1С. Верхний фильтр `Кабинет WB` берет значения из справочника кабинетов клиента,
поэтому новый кабинет виден в выборе даже до импорта первого отчета. При
переименовании кабинета связанная интеграция обновляет только безопасные
metadata вроде названия кабинета и организации; сохраненный secret не
возвращается в API и не показывается в UI.

API и audit никогда не должны возвращать полный secret. Допустимы только
provider, status, masked `secretHint`, `storageMode`, safe `lastCheck` и
timestamps. OpenAI key остается сервисным runtime secret в окружении сервиса,
клиентский BYOK не включен в текущий пилот.

Для реальных проверок должен быть задан runtime-ключ:

```text
SHUMEYKO_INTEGRATION_SECRET_KEY=<fernet-key>
```

Значение хранить только в `/etc/shumeiko-web-prod.env` или другом root-only runtime
контуре. Не записывать его в Git, Markdown, HTML, JSON или чат. Если ключ
шифрования не задан, новый tenant secret сохраняется в `hash_only` режиме:
кабинет покажет, что ключ введен, но `Проверить` вернет `check_failed` и
попросит повторно сохранить ключ после настройки secret storage.

Проверки:

- `wb_api`: легкий read-only `GET https://finance-api.wildberries.ru/ping`;
  проверяет достижимость WB API, валидность токена и Finance category, не
  читает финансовые отчеты;
- `onec_readonly`: `GET <baseUrl>/$metadata` через Basic Auth; проверяет, что
  OData endpoint и учетная запись доступны для чтения metadata.

В UI для `onec_readonly` показываются отдельные поля: `URL 1С/OData`,
`Пользователь`, `Пароль` и `Проверять SSL`. Frontend собирает их в JSON-секрет
перед отправкой в API; реальный пароль не отображается после сохранения.

Ручной формат 1С-секрета для API или отладки может быть JSON:

```json
{
  "baseUrl": "https://example.invalid/odata/standard.odata",
  "username": "readonly_user",
  "password": "secret",
  "verifySsl": true
}
```

или key-value строкой:

```text
baseUrl=https://example.invalid/odata/standard.odata;username=readonly_user;password=secret;verifySsl=true
```

Эти примеры являются placeholders. Реальные URL, логины и пароли в документах
не фиксировать.

# Live Checks

До отдельного smoke держать:

```text
SHUMEYKO_LIVE_CHECKS_ENABLED=false
```

При выключенном режиме endpoint возвращает `status=disabled` и
`reviewStatus=needs_review`. Нули вместо недоступных данных не подставляются.
Все обращения пишутся в audit и кешируются.

# 1С Auto-Refresh

Кнопка 1C auto-refresh и AI-команда дозагрузки 1С оставлены для совместимости
интерфейса, но внутри вызывают новый единый `SourceRefreshService` в режиме
`onec-only`. Новые запуски пишутся в `source_refresh_runs`, а старые
`data_refresh_jobs` остаются только историей.

До отдельного read-only smoke на реальном доступе держать:

```text
SHUMEYKO_SOURCE_REFRESH_ENABLED=false
```

После включения ручной `onec-only` refresh доступен только `consultant/admin`.
Он берет доступы из encrypted tenant integrations, читает 1С только read-only,
сохраняет snapshot в `data/source_refresh/<snapshot_set_id>/`. При
`SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true` новый `report_run` публикуется через
DB-first marts и artifact registry; при выключенном флаге остается legacy
workbook-import fallback. Исходный отчет не патчится.

# WB/1C Source Refresh

Новый контур `source refresh` обновляет raw lineage WB, 1С и mapping одним
`snapshot_set_id`. До smoke на реальных доступах держать:

```text
SHUMEYKO_SOURCE_REFRESH_ENABLED=false
```

В web-кабинете для `consultant/admin` основной ручной сценарий находится в
виджете `Интеграции` выбранного клиента, блок `Обновление данных`:

1. Сохранить и проверить WB/1С read-only подключения.
2. Если клиент новый или mapping менялся, нажать `Вставить mapping` и загрузить
   TXT/TSV/CSV выгрузку `Сопоставление товаров` из 1С.
3. Нажать `Проверить готовность` — это dry-run, без внешних WB/1С чтений и без
   публикации отчета.
4. Если проверка прошла, нажать `Запустить full` — это явный read-only refresh
   WB + 1С + mapping. Новый report публикуется только после успешной загрузки
   обязательных источников и сборки отчета.
5. Смотреть статус в этом же блоке: режим, период, safe-сообщение, новый report
   id и коллекции источников.

Клиентская роль этот блок не видит. API не возвращает секреты, raw payloads и
содержимое mapping; audit по загрузке mapping хранит только безопасное имя файла
и размер.

Если сопоставление WB ↔ 1C пока приходит не через API, консультант заходит в
web-кабинет под ролью `consultant/admin`. Когда верхняя карточка показывает
`Главное действие: Обновить mapping WB ↔ 1C`, нужно нажать `Вставить файл`,
выбрать актуальную TXT/TSV/CSV выгрузку `Сопоставление товаров` из 1С и нажать
`Обновить`. Файл сохраняется только в локальный
`SHUMEYKO_SOURCE_REFRESH_MAPPING_DIR`; содержимое файла не возвращается в API и
не публикуется клиенту. После загрузки web-кабинет автоматически запускает
staff-only source refresh/rebuild для текущего отчета. Если пересборка создала
новый `report_run`, UI открывает новую витрину сам. Если refresh занят,
отключен настройкой или завершился ошибкой, UI показывает безопасный статус;
пользователь не должен запускать refresh вручную.

Выгрузка файла в 1С:

1. Открыть раздел `Маркетплейс`.
2. В блоке `Обработки` выбрать `Сопоставление товаров`.
3. Проверить профиль нужного WB-кабинета или ИП.
4. В таблице нажать `Еще` -> `Вывести список...`.
5. В открывшемся списке нажать кнопку сохранения и выбрать текстовый формат
   `TXT`, `TSV` или `CSV`. Если 1С по умолчанию предлагает
   `Табличный документ (*.mxl)`, сменить тип файла перед сохранением.

Если readiness показывает `partial_period`, клиенту нужно явно написать, что
период предварительный, или дождаться закрытия полного периода и пересобрать
отчет. Если readiness показывает `partial_source`, сначала проверить, можно ли
дозагрузить источник; если нельзя, ограничение источника также указывается в
клиентском выводе.

Основной запуск:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/run_source_refresh.py \
  --tenant shumeyko \
  --mode full
```

Проверка конфигурации без чтения WB/1С:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/run_source_refresh.py \
  --tenant shumeyko \
  --mode full \
  --dry-run
```

Правила:

- production scheduler использует encrypted tenant integrations; `.env`
  разрешен только для ручного локального backfill через
  `--credential-source env`;
- production CLI и health helper не читают локальный `.env`; runtime settings
  берутся из systemd environment или явного `SHUMEYKO_DATABASE_URL`, а WB/1C
  секреты — из encrypted tenant integrations;
- `hash_only`, disabled или отсутствующие интеграции дают
  `needs_configuration` и не запускают внешние API;
- `daily` читает rolling window и не публикует новый report run, чтобы не
  создать обрезанный отчет;
- `weekly`/`full` читают полный настроенный период и создают новый report run
  только если обязательные источники прошли;
- ошибка WB Finance detail, 1C nomenclature/barcodes/organizations/sales
  register или mapping блокирует новый отчет;
- optional source failure, например weekly report list, дает report run со
  статусом `needs_review`;
- stale mapping подсвечивается отдельно: деньги могут сходиться, но товарные
  строки требуют проверки.
- raw rows для WB Finance, weekly report list, 1C OData и mapping metadata
  пишутся в `source_snapshot_rows` после создания collection. Ошибка записи
  raw rows по обязательному источнику блокирует публикацию, по optional source
  переводит отчет в `needs_review`.

Клиентская иерархия:

- `Шумейко и Партнеры` — consulting firm, не клиент отчета;
- текущий клиент `Мухамедов / Мухамедова` живет в `tenant=shumeyko` и имеет две
  организации/два WB-кабинета;
- второй клиент в текущей схеме заводится отдельным `tenant_id`/`client_id`;
- консультант или администратор может создать новый клиентский контур из
  верхней панели web-кабинета; роль `client` этот сценарий не видит;
- `scripts/repair_web_client_hierarchy.py` работает dry-run-first, запись только
  с `--apply`; для нового клиента передать `--tenant-id`, `--client-id`,
  `--client-name`, повторяемые `--company` и `--cabinet`.

Для systemd использовать отдельные timers: daily каждый час на 15-й минуте по
МСК для rolling raw refresh и weekly/full утром в понедельник для публикации
нового отчета после закрытия недельных данных WB/1С. Сырые snapshots остаются
в `data/source_refresh` и не публикуются клиенту.

Проверка первого scheduled run:

```bash
.venv/bin/python scripts/check_source_refresh_health.py \
  --tenant shumeyko \
  --mode daily \
  --max-age-hours 2
```

Код выхода `0` означает свежий приемлемый run, `1` — свежий
`failed/needs_configuration`, `2` — run не найден, устарел, еще выполняется или
БД недоступна. Дополнительно проверить `journalctl` по timer service: в логах не
должно быть токенов, connection strings или raw payload.

## Staff-ready анализ логистики

До проверки нового снимка оба флага должны оставаться выключенными:

```text
SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=false
SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED=false
```

Порядок test-rollout:

1. Применить additive schema через штатный `init_db` и включить только
   `SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=true` на test.
2. Запустить новый `full` source refresh с read-only WB-доступом. Витрина
   строится из сохраненных `source_snapshot_rows`, а не из ответа API на лету.
3. Открыть draft-отчет под consultant/admin. В разделе `Логистика` статус должен
   быть `ready` или явно `partial`; `blocked` нельзя обходить fallback-ключом.
4. Сверить общую сумму с текущим отчетом, покрытие ключа и товара, компоненты и
   несколько обезличенных цепочек. Старый отчет должен показывать
   `needs_rebuild`.
5. Клиентский флаг оставить `false` до отдельного согласования.

Rollback выполняется установкой
`SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=false` и перезапуском web/worker. Это скрывает
маршруты и раздел, не меняет существующие отчеты и не удаляет добавочные
витрины. Raw payload, внешние order-id и source hashes не должны появляться в
API, UI, AI-контексте или логах.

# Backup

PostgreSQL backup:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/backup_web_db.py \
  --output-dir /var/backups/shumeiko-web \
  --retention-days 3
```

Архивы backup хранятся вне Git и должны быть доступны только операционному
пользователю/root. Скрипт должен писать `pg_dump` в gzip потоково: нельзя
держать полный дамп PostgreSQL в памяти, потому что runtime-БД содержит raw
snapshot rows и может быть существенно больше доступной RAM.
Локальная ретенция ограничена тремя днями: при текущем размере dump 14-дневная
история не помещается на root-диске. Долговременные копии должны выгружаться на
другой физический диск или в объектное хранилище.

Перед массовой очисткой raw DB rows и online repack дополнительно создается
JSON-подтверждение внешней копии. Для filesystem оно содержит пути, SHA-256,
`createdAt`, `offHostVerified: true`, `restoreListChecked: true`,
`backupMount` и `backupDevice`. Оба файла находятся на mount, отличном от
PostgreSQL и `/data`. Для S3 вместо локальных путей фиксируются URI, version id,
размеры объектов, endpoint, region и bucket. Verifier повторно читает обе
зафиксированные версии, пересчитывает SHA-256 и потоково выполняет
`pg_restore --list`. Без подтверждения retention `--apply` и online repack
завершают preflight без изменений.

Пакет создается только на заранее подключенном внешнем mount:

```bash
.venv/bin/python scripts/create_maintenance_backup.py \
  --backup-mount /mnt/external-shumeyko-backup
```

Скрипт создает custom-format `database.dump`, `roles.sql`, выполняет
`pg_restore --list`, считает SHA-256 и печатает путь к
`backup-verification.json`. `/data` и PostgreSQL filesystem отклоняются.

Для приватного versioned S3 bucket используется отдельный пользователь с
правами чтения/записи только в этом bucket. Credential JSON хранится вне Git с
правами `0600`; ключи нельзя передавать через аргументы CLI или печатать в лог:

```bash
SHUMEYKO_DATABASE_URL=... \
.venv/bin/python scripts/create_maintenance_backup.py \
  --s3-config /root/.config/shumeyko/s3-backup.json \
  --roles-system-user postgres
```

Database dump и roles dump загружаются сразу из stdout PostgreSQL в multipart
S3 upload. После загрузки скрипт читает конкретные object versions обратно,
проверяет SHA-256 и `pg_restore --list`, загружает копию verification JSON в тот
же префикс и сохраняет небольшой локальный verification JSON для последующего
`prune --apply`/repack. Полный dump на root-диске не создается.
`--roles-system-user postgres` используется только на локальном PostgreSQL host,
чтобы `pg_dumpall --roles-only` мог прочитать `pg_authid`; credential приложения
для этого недостаточно.

# Marketplace raw-row migration

Теневой запуск использует:

```bash
SHUMEYKO_MARKETPLACE_DAILY_FACTS_ENABLED=true
SHUMEYKO_SOURCE_REFRESH_RAW_DB_MODE=legacy
```

После WB parity-check включается `files_only`. В этом режиме raw WB остаются в
`source_refresh_root`, а PostgreSQL получает только collection metadata и
дневную WB-витрину. Ozon параллельно строит типизированные текущие operations,
но продолжает совместимую raw-запись до отдельного parity-check. Только после
него дополнительно включается:

```bash
SHUMEYKO_SOURCE_REFRESH_OZON_FILES_ONLY_ENABLED=true
```

DB retention сначала запускается без `--apply`. Принять старые marketplace
collections как file-authoritative можно только с полной проверкой manifest и
hashes:

```bash
.venv/bin/python scripts/prune_source_refresh_database.py \
  --file-authoritative-marketplace \
  --adopt-verified-marketplace-files \
  --source-root data/source_refresh
```

После проверки dry-run destructive запуск обязательно получает внешний пакет:

```bash
.venv/bin/python scripts/prune_source_refresh_database.py \
  --file-authoritative-marketplace \
  --adopt-verified-marketplace-files \
  --source-root data/source_refresh \
  --backup-verification /var/lib/shumeiko/maintenance-backups/...-backup-verification.json \
  --apply
```

Проверяемое восстановление выполняется без API и по умолчанию является dry-run:

```bash
SHUMEYKO_SOURCE_REFRESH_RAW_DB_MODE=legacy \
.venv/bin/python scripts/restore_marketplace_raw_rows.py \
  --run-id source_refresh_xxx
```

После сверки команда повторяется с `--apply`; повторный запуск не добавляет
дубли.

После удаления и `VACUUM (ANALYZE)` физическое уменьшение выполняется один раз:

```bash
.venv/bin/python scripts/online_repack_source_snapshot_rows.py \
  --backup-verification /path/to/off-host-backup-verification.json
```

После проверки preflight команда повторяется с `--apply`. Daily, weekly и
watchdog timers должны быть остановлены; web продолжает обслуживать чтения.

# Monitor

Быстрая проверка runtime:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/check_web_cabinet_health.py
```

Проверка выводит статус systemd, local `/api/health`, количество пользователей,
количество report runs и дату последнего отчета. Секреты и database URL не
печатаются.

# Deployment Smoke

- `https://analitika.offonika.ru` открывает production login/UI по HTTPS;
- `https://analitika.offonika.ru/cabinet` открывает тот же login/UI shell;
- `https://shumeiko.offonika.ru` показывает staff-only test banner;
- `/api/health` отвечает `200`;
- unauthenticated `/api/reports` отвечает `401`;
- после login первый экран показывает readiness panel и качество отчета;
- секция `Товары` показывает фильтры, а таблица прокручивается горизонтально на
  узком экране без обрезания правых колонок;
- виджет `AI-аналитик` открывается поверх отчета, отправляет быстрые вопросы,
  показывает timeline и статус `OpenAI`/`Fallback`;
- виджет `Клиентский вывод` открывается поверх отчета без прокрутки вниз;
- `consultant/admin` открывает `Интеграции` как виджет поверх отчета; роль
  `client` его не видит;
- роль `client` не видит staff-only статус клиентского AI-черновика;
- `X-Robots-Tag: noindex, nofollow, noarchive` есть в ответах;
- secure session cookie появляется только после login;
- `/data/dashboard-data.json`, `/downloads/shumeyko_wb_excel_mvp.xlsx`,
  `/.env` не отдаются публично;
- AI-виджет открывается, а ответ явно показывает ограничения источников.
