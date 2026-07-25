---
title: "Эксплуатация web-кабинета Shumeyko"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: draft
source_of_truth: false
updated_at: "2026-07-25"
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

Legacy rollback window завершено. `shumeiko-web.service`, порт `8096`,
`/etc/shumeiko-web.env` и публичный nginx-маршрут должны отсутствовать.
Штатное состояние — активны только `shumeiko-web-prod.service` и
`shumeiko-web-test.service`. Откат выполняется переключением
`/opt/shumeyko-runtime/prod/current` на предыдущий проверенный immutable release.

Однократная очистка старого unit после подтверждения health обоих контуров:

```bash
systemctl disable --now shumeiko-web.service
rm -f /etc/systemd/system/shumeiko-web.service
rm -rf /etc/systemd/system/shumeiko-web.service.d
rm -f /etc/shumeiko-web.env
systemctl daemon-reload
systemctl reset-failed
```

Оба локальных процесса контролируются отдельными timers:

```bash
systemctl status shumeiko-web-prod-health.timer
systemctl status shumeiko-web-test-health.timer
systemctl start shumeiko-web-prod-health.service
systemctl start shumeiko-web-test-health.service
```

Проверка считается успешной только при `status=ok`, правильном
`runtimeEnvironment` и одинаковых `backendBuildId`/`staticBuildId`.

После изменения systemd/nginx или очистки временных drop-in’ов проверить drift:

```bash
.venv/bin/python scripts/check_runtime_contour_drift.py
```

Проверка не читает EnvironmentFiles и должна завершаться без расхождений.

## Environment files

Production environment задает `SHUMEYKO_RUNTIME_ENVIRONMENT=production`,
`SHUMEYKO_CLIENT_LOGIN_ENABLED=true`, отдельное имя cookie и
`SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED=true`. Test environment задает
`SHUMEYKO_RUNTIME_ENVIRONMENT=test`, `SHUMEYKO_CLIENT_LOGIN_ENABLED=false`,
отдельную test БД/report root/source root и по умолчанию
`SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED=false`.

Report roots разделены и не находятся в Git checkout:

- production: `/data/shumeyko/prod/reports`;
- test: `/data/shumeyko/test/reports`.

Перед первым переключением production создать новый каталог и скопировать
действующие artifacts без удаления старого root:

```bash
install -d -m 0750 /data/shumeyko/prod/reports
rsync -a /opt/shumeyko-partners-wb-unit-economics/reports/ \
  /data/shumeyko/prod/reports/
```

С 23 июля 2026 года отдельный tracked R-6 override включает client login и
логистику F-1…F-5 только на test. Он не меняет EnvironmentFile и закрепляет
разрешённые booleans через `ExecStart=/usr/bin/env`, потому что systemd читает
EnvironmentFile позже `Environment=`. Точное operational state и rollback
записаны в `docs/runbooks/wb-logistics-v4-continuation.md`.

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
- `/accounting-workflows`;
- `/static/*`;
- `/api/*`.

Старый статический shell из `/var/www/offonika-shumeiko/shumeiko/index.html`
нельзя использовать для web-кабинета: он хранит устаревший контракт и может
обращаться к `unitRows` из public summary. Актуальный nginx-шаблон лежит в
`deploy/nginx/analitika.offonika.ru.conf` и
`deploy/nginx/shumeiko.offonika.ru.conf`.

Test nginx проксирует только известные FastAPI routes. Любой другой route
возвращает `404`; fallback на файлы из `/var/www/offonika-shumeiko` запрещён.

Маршрут `/accounting-workflows` должен проксироваться в FastAPI даже при
выключенном feature-флаге. В этом случае backend вернёт штатный `404`; nginx не
должен подменять его старым статическим shell.

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

## Генерация бухгалтерских отчётов из кабинета

Основной путь сборки `month_close_control` и `tax_load` — кнопка «Сформировать
отчёт» в самом кабинете (staff-only). Оператор выбирает клиента, организацию 1С,
календарный месяц и вид отчёта; кнопка активна, когда заданы организация и месяц.
Клик вызывает `POST /api/clients/{client_id}/reports/generate`
(`reportKind/organizationId/periodMonth`, заголовок `Idempotency-Key`); сервис
создаёт generation run и запускает тот же worker в фоне — отдельные команды не
нужны. CLI ниже — только аварийный/canary путь без UI.

Для вида «Налоговая нагрузка» у ИП на УСН официальный коэффициент ФНС остаётся
`null` (нет отчёта о финансовых результатах). Для объекта `УСН Доходы`
отдельно показывается управленческий `usn_income_tax_burden` от подтвержденных
поступлений без НДС, а КУДиР используется как YTD-сверка. Для объекта
`УСН Доходы минус расходы` применяется методика `usn_income_expenses_v1`:
признанные доходы и расходы берутся только из ресурсов `ДоходБаза` и
`РасходБаза` КУДиР, ставка — из налогового профиля 1С, минимальный налог 1%
до декабря показывается справочно. Банковские движения в этом режиме остаются
контрольными потоками и не подменяют КУДиР.

Если расчёт Д−Р пуст, проверить, что refresh собрал `onec_kudir`, OData 1С
отдаёт `ДоходБаза`, `РасходБаза` и `ВидЗаписи`, а налоговый профиль содержит
`taxRate`. Missing/partial источник оставляет базу и налог пустыми; ноль не
подставляется. Сохранённый payload до `tax-load-report-v7` требует повторного
формирования.

Для canary до клиентской публикации staff-run можно поставить в очередь через
тот же runtime-контур, не выводя organization ID или учетные данные. Для
production используются production runtime и EnvironmentFile, для test —
`/opt/shumeyko-runtime/test/current` и `/etc/shumeiko-web-test.env`; смешивать
EnvironmentFile разных контуров запрещено:

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

Для временной staff-only проверки `tax_load` без полного источника платежей
можно добавить информационный график из локального черновика. Команда работает
только в runtime environment `test`, не печатает суммы или названия строк и по
умолчанию выполняет dry-run:

```bash
systemd-run --wait --collect --pipe \
  --unit=shumeiko-tax-load-draft-reference \
  --property=WorkingDirectory=/opt/shumeyko-runtime/test/current \
  --property=EnvironmentFile=/etc/shumeiko-web-test.env \
  /opt/shumeyko-runtime/test/current/.venv/bin/python \
  scripts/attach_tax_load_draft_reference.py \
  --report-id '<tax_load report_id>' \
  --workbook '<локальный reports/...xlsx>' \
  --workbook-root '<разрешенный локальный reports>' \
  --apply
```

Импортированные строки всегда получают `partial_source`, не участвуют в
коэффициенте ФНС и не заменяют бухгалтерскую проверку. Повторный запуск
идемпотентно заменяет только reference-строки этого типа; подтвержденные
`tax_rows` скрипт менять отказывается.

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

Если для production одобрен корпоративный proxy, установить versioned drop-in
`deploy/systemd/shumeiko-web-prod.service.d/corporate-proxy-login-shell.conf`.
Он запускает uvicorn через root login profile, где хранится proxy, не дублируя
его URL и credentials в unit или EnvironmentFile. Применение и откат:

```bash
sudo install -D -m 0644 \
  deploy/systemd/shumeiko-web-prod.service.d/corporate-proxy-login-shell.conf \
  /etc/systemd/system/shumeiko-web-prod.service.d/corporate-proxy-login-shell.conf
sudo systemctl daemon-reload
sudo systemctl restart shumeiko-web-prod.service

# rollback
sudo rm /etc/systemd/system/shumeiko-web-prod.service.d/corporate-proxy-login-shell.conf
sudo systemctl daemon-reload
sudo systemctl restart shumeiko-web-prod.service
```

После применения проверять HTTP-клиентом Python/SDK OpenAI, а не только
`curl`: shell profile не наследуется обычным systemd ExecStart.

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
   WB + 1С + mapping. После успешной загрузки обязательных источников и сборки
   создаётся внутренний staff draft; текущий опубликованный отчёт не меняется.
5. Смотреть статус в этом же блоке: режим, период, safe-сообщение, новый report
   id и коллекции источников.
6. Проверить период, coverage, обязательные источники и финансовые замечания,
   затем отдельным audited-действием финансовой приёмки опубликовать draft как
   current. Без этого действия предыдущий current остаётся клиентским отчётом.

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
- `weekly`/`full` читают полный настроенный период и создают новый staff draft
  только если обязательные источники прошли; автоматической публикации current
  нет;
- ошибка WB Finance detail, 1C nomenclature/barcodes/organizations/sales
  register или mapping блокирует новый отчет;
- optional source failure, например weekly report list, дает report run со
  статусом `needs_review`;
- stale mapping подсвечивается отдельно: деньги могут сходиться, но товарные
  строки требуют проверки.
- raw rows для WB Finance, weekly report list, 1C OData и mapping metadata
  пишутся в `source_snapshot_rows` после создания collection. Ошибка записи
  raw rows по обязательному источнику блокирует создание готового draft, по
  optional source переводит draft в `needs_review`.

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
МСК для rolling raw refresh и weekly/full утром в понедельник для создания
нового staff draft после закрытия недельных данных WB/1С. Сырые snapshots
остаются в `data/source_refresh` и не публикуются клиенту.

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

Code defaults остаются выключенными:

```text
SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=false
SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED=false
SHUMEYKO_LOGISTICS_FACTORS_ENABLED=false
SHUMEYKO_LOGISTICS_FACTORS_CLIENT_ENABLED=false
SHUMEYKO_LOGISTICS_MEASUREMENTS_ENABLED=false
SHUMEYKO_LOGISTICS_MEASUREMENTS_CLIENT_ENABLED=false
SHUMEYKO_LOGISTICS_TARIFFS_ENABLED=false
SHUMEYKO_LOGISTICS_TARIFFS_CLIENT_ENABLED=false
SHUMEYKO_LOGISTICS_ROUTES_ENABLED=false
SHUMEYKO_LOGISTICS_ROUTES_CLIENT_ENABLED=false
SHUMEYKO_LOGISTICS_RETURN_REASONS_ENABLED=false
SHUMEYKO_LOGISTICS_RETURN_REASONS_CLIENT_ENABLED=false
```

Фактическое состояние test/production перед rollout проверяется по
`docs/runbooks/wb-logistics-v4-continuation.md` и свежему environment evidence,
а не по defaults. Для v5 нельзя включать production или клиентский флаг без
отдельного разрешения.

Порядок test-rollout:

1. Применить additive schema migration
   `2026_07_18_logistics_profit_link_v5` через штатный `init_db`. Убедиться, что
   `SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true`; master-флаг без DB-first является
   ошибкой конфигурации и source refresh не запускается.
2. Включить только `SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=true` на test.
3. Запустить новый `full` source refresh с read-only WB-доступом. Витрина
   строится из сохраненных `source_snapshot_rows`, а не из ответа API на лету.
4. Открыть новый draft-отчет под consultant/admin. Контекст должен иметь
   `methodologyVersion=wb-logistics-v5` и
   `chainKeyVersion=wb-order-product-v1`. `blocked`, отсутствующий, v1–v4 или
   несовместимый по ключу контекст нельзя обходить fallback-ключом или ручной
   публикацией.
5. Проверить `reportCoverage`: source/report invalid-строки,
   `chainDimensionConflicts`, `invalidSourcePayloadShapes`,
   `sourceIdentityErrors`, `sourceRevisionConflicts`, `scopeMismatches`,
   unmatched dimensions и `maxDimensionDelta`;
   затем сверить точные календарные срезы, компоненты и несколько обезличенных
   цепочек по `productRef`. На части недели логистика должна оставаться точной,
   а финансовые KPI — `null`.
   Отдельно проверить HTTP 400 `invalid_logistics_period` для инвертированного
   диапазона и дат вне периода report run.
6. Старый необязательный отчет должен показывать `needs_rebuild`, но не получать
   новый publication blocker. Клиентский флаг оставить `false` до отдельного
   согласования.

Для staff-only F-1 «Габариты» поверх готовой первой очереди дополнительно:

1. Применить additive migration
   `2026_07_20_logistics_dimensions_context_v1` через тот же штатный `init_db`.
2. Включить на test только `SHUMEYKO_LOGISTICS_FACTORS_ENABLED=true`;
   `SHUMEYKO_LOGISTICS_FACTORS_CLIENT_ENABLED` явно оставить `false`.
3. Создать новый immutable draft из verified `wb_product_cards` snapshot.
   Context обязан иметь `factorMethodologyVersion=wb-logistics-factors-v1`;
   integrity/scope failure даёт non-overridable blocker без dimension rows,
   а неполные габариты остаются review-состоянием без нулевой подстановки.
4. Под staff проверить `/logistics/dimensions`, desktop/mobile секцию между
   финансовой аналитикой и рейтингом товаров и локальное error-состояние.
   Под client-ролью factor API обязан вернуть HTTP 404, секция не показывается
   и запрос не выполняется. Production и client factor flag не включать.

Для staff-only F-2 «Тарифы» после F-1 дополнительно:

1. Применить additive migration
   `2026_07_21_logistics_tariffs_context_v1` через штатный `init_db`.
2. Оставить factor master включённым и включить на test только
   `SHUMEYKO_LOGISTICS_TARIFFS_ENABLED=true`; оба client-флага factors/tariffs
   явно оставить `false`.
3. Выполнить новый full source refresh. `wb_tariffs` обязан иметь verified
   manifest и статусы каждой недельной даты; 429/недоступный архив даёт
   `partial`, а не нулевую ставку.
4. Создать новый immutable draft и проверить
   `factorMethodologyVersion=wb-logistics-tariffs-v1`, `/logistics/tariffs`,
   desktop/mobile блок после габаритов и локальную ошибку. Под client API
   обязан вернуть 404, запрос и секция отсутствовать. Production и client
   enable не выполнять.

Для staff-only F-3 «Склады и направления» после F-2 дополнительно:

1. Применить additive migration
   `2026_07_21_logistics_routes_context_v1` через штатный `init_db`.
2. Оставить factor master включённым и включить на test только
   `SHUMEYKO_LOGISTICS_ROUTES_ENABLED=true`; client-флаги factors/routes
   явно оставить `false`.
3. Выполнить новый full source refresh из verified `wb_supplier_sales`
   snapshot, создать immutable draft и проверить
   `factorMethodologyVersion=wb-logistics-routes-v1` и `/logistics/routes`.
4. Под staff проверить desktop/mobile блок, exact route evidence и локальную
   ошибку. Под client API обязан вернуть 404, запрос и секция отсутствовать.
   Production и client enable не выполнять.

Для staff-only F-4 «Замеры и удержания» после успешного source gate:

1. Применить additive migration
   `2026_07_21_logistics_measurements_context_v1` через штатный `init_db`.
2. Оставить factor master включённым и включить на test только
   `SHUMEYKO_LOGISTICS_MEASUREMENTS_ENABLED=true`;
   `SHUMEYKO_LOGISTICS_MEASUREMENTS_CLIENT_ENABLED=false`.
3. Выполнить новый full source refresh. Оба Analytics source type обязаны
   пройти manifest/hash/row-count/provider-total проверку; недоступный endpoint
   даёт `partial`, integrity/scope failure — `blocked` context без rows.
4. Создать новый immutable draft и проверить
   `factorMethodologyVersion=wb-logistics-measurements-v1`,
   `/logistics/measurements` и отсутствие повторного учёта сумм в финансовых
   KPI. Под client API обязан вернуть 404, запрос и секция отсутствовать.
5. Выполнить browser-приёмку 1440×900 и 390×844 без overflow и
   console/page/network errors. Production и client enable не выполнять.

Для R-3 F-5 «Причины возвратов» после merge кода, но до R-4 UI:

1. Применить additive migration
   `2026_07_23_logistics_return_reasons_context_v1` через штатный `init_db`.
2. Оставить logistics/factors master включёнными и включить на test только
   `SHUMEYKO_LOGISTICS_RETURN_REASONS_ENABLED=true`;
   `SHUMEYKO_LOGISTICS_RETURN_REASONS_CLIENT_ENABLED=false`.
3. Выполнить новый full source refresh из verified Finance, goods-return и
   claims snapshots. Empty/denied claims должны дать явный
   `partial/data_unavailable`, но не publication blocker; integrity/scope/
   reconciliation failure должен дать `blocked` context без mart rows.
4. На новом immutable draft проверить
   `methodologyVersion=wb-logistics-return-reasons-v1`,
   `/logistics/return-reasons`, SQL-фильтры/сортировки/пагинацию, coverage
   полного среза и отсутствие raw `srid`, source hashes, claim IDs,
   комментариев и media. Client API обязан вернуть HTTP 404.
5. R-3 не содержит UI. Browser-приёмку секции, test staff acceptance,
   production и client enable выполнять только в R-4/R-5 по отдельному
   разрешению.

Для R-5 staff-only acceptance после merge R-4:

1. Собрать immutable release из точного merge-коммита `main`; manifest обязан
   подтверждать `sourceDirty=false`. Не откатывать test на более старый runtime,
   если после R-4 в `main` уже влиты другие совместимые изменения.
2. Повторно идемпотентно применить additive migration
   `2026_07_23_logistics_return_reasons_context_v1`, атомарно переключить только
   test symlink и перезапустить только `shumeiko-web-test.service`.
3. Установить tracked test drop-in
   `deploy/systemd/shumeiko-web-test.service.d/zz-logistics-r5-return-reasons.conf`.
   Он включает F-1…F-5 только для staff и явно оставляет все client-флаги
   `false`, даже если более ранний drop-in включал client-доступ.
4. Выполнить новый test-only `full` source refresh с read-only интеграциями и
   отдельным immutable draft. Для test использовать foreground/background
   worker текущего test runtime; production worker unit с production
   EnvironmentFile не запускать. Empty/denied claims дают
   `partial/data_unavailable`, но не publication blocker.
5. Проверить staff `/api/me`, HTTP 200
   `/logistics/return-reasons`, methodology
   `wb-logistics-return-reasons-v1`, coverage полного SQL-среза,
   сортировку/пагинацию и отсутствие raw IDs, hashes, комментариев и media.
   Под client API обязан вернуть HTTP 404, секция должна отсутствовать и request
   не должен выполняться.
6. Выполнить browser-smoke 1440×900 и 390×844 по прямой ссылке на разрешённый
   draft: без page overflow, console/page/network errors и stale/zero fallback.
   Draft не публиковать; production runtime, service и flags не менять.
7. После приёмки удалить временные sessions, credential-файлы, browser script и
   screenshots; временных пользователей деактивировать и сбросить им пароли.

Для отдельного R-6 client-role rollout после принятого R-5:

1. Собрать immutable release из точного commit с `sourceDirty=false` и
   переключить только test symlink.
2. Установить tracked drop-in
   `deploy/systemd/shumeiko-web-test.service.d/zzz-logistics-r6-client-test.conf`
   в одноимённый каталог `/etc/systemd/system`. Он обязан применяться после
   R-5 drop-in и включать client login, master/client flags основной логистики,
   F-1, F-2, F-3, F-4 и F-5.
3. Выполнить `systemctl daemon-reload`, перезапустить только
   `shumeiko-web-test.service` и проверить `status=ok`, test environment,
   совпадающие backend/static build и неизменный production PID/symlink.
4. Под временной client-role проверить `/api/me`, HTTP 200 F-1…F-5 API,
   видимость только current published report, HTTP 404 для draft, чужого
   client/tenant scope и staff-only `/logistics/orders`.
5. Проверить отсутствие raw IDs, source/input hashes, claim IDs, текста
   комментариев, media/photo URLs. Безопасный агрегатный quality counter не
   считается передачей исходного identifier.
6. Выполнить authenticated browser-smoke 1440×900 и 390×844: все секции
   F-1…F-5 видимы, staff orders скрыты, required requests отвечают 200, нет
   page/workspace overflow и console/page/network errors.
7. Draft не публиковать. После приёмки сбросить пароли, деактивировать временных
   users, удалить sessions, credentials, screenshots и transient units.

Rollback R-6: удалить только
`/etc/systemd/system/shumeiko-web-test.service.d/zzz-logistics-r6-client-test.conf`,
выполнить `systemctl daemon-reload` и перезапустить только test web. R-5
staff-only drop-in остаётся установленным; reports, marts, production и внешние
источники не изменяются.

Rollback выполняется установкой
`SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=false` и перезапуском web/worker. Это скрывает
маршруты и раздел, не меняет существующие отчеты и не удаляет добавочные
витрины. Rollback не снимает publication blocker с нового report run, который
обязан был пройти gate, но не прошел его. Для исправления создается новый report
run; повторный импорт того же `report_id` запрещен. Raw payload, внешние
order-id и source hashes не должны появляться в API, UI, AI-контексте или логах.
Частичный rollback F-1 выполняется отдельно:
`SHUMEYKO_LOGISTICS_FACTORS_ENABLED=false`; первая очередь логистики при этом
остаётся доступной.
Частичный rollback F-2 —
`SHUMEYKO_LOGISTICS_TARIFFS_ENABLED=false`; F-1 и первая очередь остаются
доступными, а required blocker уже созданного draft не снимается.
Частичный rollback F-3 —
`SHUMEYKO_LOGISTICS_ROUTES_ENABLED=false`; остальные factor-блоки не меняются.
Частичный rollback F-4 —
`SHUMEYKO_LOGISTICS_MEASUREMENTS_ENABLED=false`; F-1/F-2/F-3 и первая очередь
остаются доступными, а required blocker уже созданного draft не снимается.
Частичный rollback F-5/R-5 —
`SHUMEYKO_LOGISTICS_RETURN_REASONS_ENABLED=false`; основная логистика и F-1…F-4
остаются доступными, additive mart не удаляется, required blocker уже
созданного draft не снимается.

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
но продолжает совместимую raw-запись до отдельного parity-check. После
безопасного deploy сначала включается typed shadow:

```bash
SHUMEYKO_SOURCE_REFRESH_OZON_TYPED_FACTS_ENABLED=true
```

После полной legacy parity qualification дополнительно включается:

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

# Operational evidence: fallback себестоимости из `Запасов` — 24 июля 2026 года

После явного разрешения пользователя на production rollout PR
[#65](https://github.com/Offonika/Ai_analitik/pull/65) влит в `main` merge-коммитом
`750e4a5429c5601ab03285a863e97189c5bd2aad`. На PR и merge-коммите GitHub CI
создал и успешно завершил оба блокирующих job: `quality` и `tests`.

Из merge-коммита собран immutable release
`runtime-main-750e4a5-stock-cost-fallback-20260724`; manifest подтверждает
`sourceDirty=false`. Перед migration создан потоковый production backup
`/var/backups/shumeiko-web/shumeiko-web-20260724_082833.sql.gz` размером
`2 625 399 876` байт, с правами `0600`; `gzip -t` завершился успешно.
Additive migration подняла production schema до
`2026_07_23_logistics_return_reasons_context_v1`. Production symlink атомарно
переключен на новый release, перезапущен только
`shumeiko-web-prod.service`.

Локальный и публичный `/api/health` после restart вернули `status=ok`,
`runtimeEnvironment=production` и одинаковые build ID. Public smoke подтвердил
FastAPI shell, HTTP 401 для неавторизованного `/api/reports`,
`X-Robots-Tag: noindex, nofollow, noarchive` и HTTP 404 для `/.env`.

Из нового runtime выполнен read-only full source refresh
`source_refresh_205e6d0e5d874cc195e0a537d60d0780`, snapshot set
`full-20260724-115121`, период `2026-03-01` — `2026-07-23`. Все обязательные
WB/1С-коллекции загрузились; итоговый `needs_review` обусловлен существующими
mapping-задачами и явными optional-source предупреждениями, health refresh
остался `ok`. Создан неопубликованный immutable draft
`shumeyko_source_refresh_20260724_090120` с восемью artifact records;
`publication_status=draft`, `is_current=false`.

Сверка одинаковых `12 227` строк предыдущего и нового draft подтвердила:

- `Нет себестоимости 1С`: `1 051` → `922` строки, `221` → `186` SKU;
- `Себестоимость 1С требует сверки`: `842` → `971` строка,
  `222` → `257` SKU;
- метод `stock_register_fixed_receipt_fallback_needs_review` применен к
  `335` строкам / `44` SKU;
- `35` ранее отсутствовавших SKU получили резервную стоимость из регистра
  `Запасы`.

Опубликованный клиентский current report этим rollout не переключался.
Rollback runtime выполняется возвратом production symlink на
`runtime-2afb91e-contours-cleanup-20260724` и restart только production web;
additive schema и созданный draft при rollback не удаляются.

## Corrective rollout статуса нулевых fallback-строк

Production-сверка первого draft выявила, что из `335` строк с методом
`stock_register_fixed_receipt_fallback_needs_review` статус
`Себестоимость 1С требует сверки` имели только `129` ненулевых строк, а `206`
строк с взаимно погашенными продажами и возвратами получили `ОК`. PR
[#66](https://github.com/Offonika/Ai_analitik/pull/66) сохранил
`needs_review` для нулевых строк, но контрольный неопубликованный draft показал
слишком широкое действие правила: общее количество строк проверки выросло до
`3 546`, включая `2 575` экономически не примененных стоимостных слоев других
методов. Этот draft не публиковался.

PR [#67](https://github.com/Offonika/Ai_analitik/pull/67) сузил правило:
нулевая строка по-прежнему не создает ложный `missing_cost`, специальный
fallback из `Запасов` всегда сохраняет `needs_review`, а иные технически
подобранные, но не попавшие в COGS стоимостные слои не создают отдельную
задачу. На PR и merge-коммите
`6e778e2c5ec0d1916fe76fd36cec20daaedd48f4` GitHub CI успешно завершил оба
блокирующих job: `quality` и `tests`.

Из merge-коммита собран immutable release
`runtime-main-6e778e2-stock-fallback-zero-net-scope-20260724`; manifest
подтверждает `sourceDirty=false`. Production symlink атомарно переключен на
него, перезапущен только `shumeiko-web-prod.service`. Schema осталась
`2026_07_23_logistics_return_reasons_context_v1`, локальный и публичный
`/api/health` вернули `status=ok` и `runtimeEnvironment=production`.

После transient `ReadTimeout` планового daily refresh выполнен read-only retry
`source_refresh_9d7d8b07f65442359a60c6ad2a1f07fb`; все обязательные источники
загрузились, source-refresh health вернулся в приемлемый `needs_review`, а
общий `/api/health` — в `ok`.

Финальный read-only full refresh
`source_refresh_ded28bb464d5403abed6cb7997d23596`, snapshot set
`full-20260724-143223`, создал неопубликованный draft
`shumeyko_source_refresh_20260724_114209` с восемью artifact records. На
одинаковых `12 227` строках проверка подтвердила:

- `Нет себестоимости 1С`: `922` строки / `186` SKU;
- `Себестоимость 1С требует сверки`: `1 177` строк / `266` SKU;
- fallback из `Запасов`: `335` строк / `44` SKU, все `335` имеют
  `Себестоимость 1С требует сверки`, строк `ОК` нет;
- из fallback-строк `206` имеют нулевое итоговое количество, и все они
  сохраняют задачу сверки.

После явного разрешения пользователя и записи финансового подтверждения в
audit report `shumeyko_source_refresh_20260724_114209` опубликован:
`publication_status=published`, `is_current=true`. Предыдущий current report
`shumeyko_source_refresh_20260713_135304` переведен в `superseded`.

Для опубликованного report повторно сформированы клиентские DOCX/PDF и
зарегистрирован проверенный Excel
`source_refresh/source_refresh_ded28bb464d5403abed6cb7997d23596/shumeyko_wb_excel_mvp.xlsx`
с SHA-256
`259a094ffa32d6a3520bf021cff309579de4e7fe328e1b944ee7697344456fa0`.
PDF имеет сигнатуру `%PDF-`; оба пути разрешаются через
`repository.report_artifact_path()` внутри production export-root
`/data/shumeyko/prod/reports`.

Проверка из production runtime командой
`scripts/check_db_first_publication.py` с ожидаемыми `12 227` строками,
`163` строками упущенных продаж и `11` ready artifacts завершилась
`Health: ok`. Найдены все обязательные типы: CSV, DOCX, Excel, HTML и PDF.
Локальный и публичный `/api/health` возвращают `status=ok` и показывают новый
report как `latestPublishedReportId`.

Технический rollback runtime — возврат production symlink на
`runtime-main-d6ff3d5-cost-review-zero-net-20260724` и restart только
`shumeiko-web-prod.service`. Публикационный rollback выполняется отдельным
возвратом предыдущего проверенного report в `published/current`; уже созданные
immutable artifacts при rollback не удаляются.

## Corrective rollout раздельных счетчиков себестоимости

24 июля 2026 года PR
[#69](https://github.com/Offonika/Ai_analitik/pull/69) разделил в
`summary.quality` отсутствующую себестоимость и предварительную себестоимость,
требующую сверки. Совместимый `missingCostRows` сохранен как общий счетчик
cost-review workflow; UI больше не подписывает его целиком как
`Без себестоимости`. На PR оба обязательных GitHub CI job, `quality` и `tests`,
завершились успешно. PR влит в `main` merge-коммитом
`880a2148d0f6988c5a7ac930d5351334cfdf67f9`.

Из merge-коммита собран immutable release
`runtime-main-880a214-cost-quality-split-20260724`; manifest подтверждает
`sourceDirty=false`. В 16:44 MSK production symlink атомарно переключен на
release, перезапущен только `shumeiko-web-prod.service`. Миграция и
пересборка отчета не выполнялись: schema осталась
`2026_07_23_logistics_return_reasons_context_v1`, опубликованный current report
остался `shumeyko_source_refresh_20260724_114209`.

Read-only проверка `report_summary_payload()` из нового runtime над
production-БД вернула:

- `rowCount=12 227`, `okRows=9 919`;
- совместимый агрегат `missingCostRows=1 893`;
- `costAbsentRows=922`;
- `costRequiresReviewRows=971`.

Еще `206` fallback-строк из регистра `Запасы` имеют нулевое итоговое количество
и сохраняют отдельную задачу сверки, но по принятой методике не входят в
финансовый `missingCostRows`. Поэтому верхняя диагностика показывает
`922` как `Без себестоимости` и `971` как `Требует сверки`, не выдавая
`1 893` за полностью отсутствующую стоимость.

Локальный и публичный `/api/health` вернули `status=ok`,
`backendBuildId=staticBuildId=20260724-cost-quality-split-v1` и тот же current
report. Public shell отдает новый cache-busting build ID, а загруженный
`app.js` содержит отдельные подписи `Стоимость не найдена` и
`Стоимость рассчитана предварительно`. Неавторизованный `/api/reports`
возвращает HTTP 401, `/.env` — HTTP 404, `X-Robots-Tag` остался
`noindex, nofollow, noarchive`. `scripts/check_web_cabinet_health.py`, запущенный
через production `EnvironmentFile` без вывода его содержимого, завершился
успешно: service, HTTP health и PostgreSQL database имеют статус `ok`.

Технический rollback — атомарно вернуть production symlink на
`runtime-main-6e778e2-stock-fallback-zero-net-scope-20260724` и перезапустить
только `shumeiko-web-prod.service`. Отчеты, artifacts и schema при таком
rollback не меняются.

## Выравнивание test после corrective rollout себестоимости

24 июля 2026 года после merge PR
[#70](https://github.com/Offonika/Ai_analitik/pull/70) локальный `main`
fast-forward обновлен до `9ad7e88`. Test symlink атомарно переключен на уже
проверенный production artifact
`runtime-main-880a214-cost-quality-split-20260724`; перезапущен только
`shumeiko-web-test.service`. Предыдущий test artifact
`runtime-2afb91e-contours-cleanup-20260724` сохранен для rollback.

После переключения оба локальных `/api/health` вернули `status=ok`,
`backendBuildId=staticBuildId=20260724-cost-quality-split-v1` и schema
`2026_07_23_logistics_return_reasons_context_v1`; окружения остались разными:
`production` на 8097 и `test` на 8098. Оба штатных health service завершились с
`Result=success`. В test client login остается выключен, активных
client-пользователей нет, неизвестный маршрут и `/.env` возвращают HTTP 404,
неавторизованный `/api/reports` — HTTP 401. Порт 8096 и legacy unit отсутствуют,
а `scripts/check_runtime_contour_drift.py` проходит без расхождений.

Rollback test — атомарно вернуть `/opt/shumeyko-runtime/test/current` на
`runtime-2afb91e-contours-cleanup-20260724` через
`scripts/promote_runtime_release.py --environment test`, перезапустить только
`shumeiko-web-test.service` и повторить test health/safety smoke.

## Test-rollout product-level mapping aliases

25 июля 2026 года PR
[#75](https://github.com/Offonika/Ai_analitik/pull/75) с fail-closed
проекцией accepted current mapping на product-level ключ WB влит в `main`
merge-коммитом `2332a347d2d560718f7c0e09ca60624c8b83329f`. На PR и после
merge в `main` оба обязательных GitHub CI job, `quality` и `tests`,
завершились успешно. На head PR команда
`.venv/bin/python -m pytest -q` вернула `1058 passed`.

Из точного merge-коммита собран immutable release
`runtime-main-2332a34-mapping-alias-fallback-20260725`; manifest подтверждает
`sourceDirty=false`, source commit `2332a347d2d560718f7c0e09ca60624c8b83329f`
и content SHA-256
`3bbb7a26d73c6df14c897f80e03eaca8e8666a1bdf026b8e6e4016f8f0a45af2`.
Атомарно переключен и перезапущен только test. Production остался на
`runtime-main-880a214-cost-quality-split-20260724`; production PID `3466421`
не изменился.

Первый test-only full после rollout завершился до тяжелых WB-загрузок
управляемой ошибкой `onec_odata_metadata_unavailable: ReadTimeout` и не создал
report. После успешного штатного production daily run
`source_refresh_3efeca9436fa401ab210ebdcc3e4f501` повторный test-only full
`source_refresh_2f0bd99ec44d45f69c9efe2d07b8aac8` получил валидный
`HTTP 200` для 1С OData metadata, собрал `48` source loads и завершился
`needs_review`, создав новый staff-only draft
`shumeyko_source_refresh_20260725_013916`. Draft имеет
`publication_status=draft`, `is_current=false`; прежний test current report
не менялся. Промежуточный draft на предыдущем immutable source snapshot также
остался непublished и может быть удален штатным retention после приёмки live
draft.

Read-only SQL-агрегаты test-БД на runtime revision `2332a347` воспроизводят
для live draft:

- период отчета `2026-03-01` — `2026-07-24`, source coverage до `2026-07-24`;
- `12 227` строк, последняя закрытая неделя начинается `2026-07-13`;
- `10 047` строк `ОК`, `1 556` строк с себестоимостью на сверку,
  `559` строк без себестоимости и `65` строк без сопоставления WB ↔ 1С;
- ненулевая себестоимость у `6 700` строк, логистика у `11 154`, налог у
  `7 358`;
- `6` месячных сверок и `157` строк документной сверки;
- logistics context `ready`, `max_dimension_delta=0`;
- все зарегистрированные CSV/DOCX/Excel/HTML artifacts имеют статус `ready`.

Ключевые агрегаты воспроизводятся без чтения raw payloads:

```sql
\set report_id 'shumeyko_source_refresh_20260725_013916'

SELECT count(*) AS rows,
       min(week) AS min_week,
       max(week) AS max_week,
       count(*) FILTER (WHERE cost <> 0) AS nonzero_cost_rows,
       count(*) FILTER (WHERE logistics <> 0) AS nonzero_logistics_rows,
       count(*) FILTER (WHERE usn <> 0) AS nonzero_tax_rows
FROM wb_unit_economics.report_unit_rows
WHERE report_run_id = :'report_id';

SELECT status, count(*)
FROM wb_unit_economics.report_unit_rows
WHERE report_run_id = :'report_id'
GROUP BY status
ORDER BY count(*) DESC;

SELECT publication_status, is_current, source_snapshot_set_id
FROM wb_unit_economics.report_runs
WHERE id = :'report_id';

SELECT count(*)
FROM wb_unit_economics.report_reconciliation_monthly
WHERE report_run_id = :'report_id';
```

После live full локальный и публичный test `/api/health` вернули `status=ok`,
`runtimeEnvironment=test`, одинаковые backend/static build ID и
`latestSourceRefreshStatus=needs_review`. Оба штатных health service завершились
с `Result=success`. В test client login выключен, активных client-пользователей
`0`, неизвестный маршрут и `/.env` возвращают HTTP 404, неавторизованный
`/api/reports` — HTTP 401. `scripts/check_runtime_contour_drift.py` проходит
без расхождений. Публичный production `/api/health` также возвращает
`status=ok`; production report, runtime symlink и web PID не менялись.

Rollback test — атомарно вернуть `/opt/shumeyko-runtime/test/current` на
`runtime-main-f5cf057-mapping-alias-fix-20260724` через
`scripts/promote_runtime_release.py --environment test`, перезапустить только
`shumeiko-web-test.service` и повторить test health/safety smoke. Draft reports,
source snapshots и production при runtime rollback не изменяются.
