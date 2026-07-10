---
spec_id: "wb-unit-economics-source-refresh-hardening-provider-registry"
title: "Shumeyko source refresh hardening and provider registry"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
related_code:
  - src/wb_unit_economics/web/app.py
  - src/wb_unit_economics/web/source_refresh.py
  - src/wb_unit_economics/web/providers.py
  - src/wb_unit_economics/web/static/app.js
  - scripts/prune_source_refresh.py
related_tests:
  - tests/test_web_app.py
  - tests/test_source_refresh.py
  - tests/test_provider_registry.py
  - tests/test_source_refresh_prune.py
contracts: [wb_api_snapshot, onec_unf_cost_snapshot, sku_mapping, unit_economics_report]
depends_on:
  - docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md
  - docs/specs/wb-unit-economics-db-first-report-marts.md
supersedes: []
rollout_required: true
updated_at: "2026-07-10"
---

# Goal

Стабилизировать регулярный `source_refresh` перед расширением read-only
интеграций и убрать hard-code WB/1C из API/UI слоя подключений.

# Scope

Входит:

- preflight guard по свободному месту до внешних WB/1C чтений;
- блокировка конфликтующих запусков `source_refresh`;
- dry-run prune CLI для старых raw snapshot directories;
- provider registry для read-only интеграций;
- metadata в `GET /api/integrations`;
- collector contract для текущих источников refresh.
- staff-only UI/API в разделе интеграций для загрузки mapping, dry-run проверки
  и ручного `full` refresh по выбранному клиентскому контуру.
- live metadata guard 1С перед тяжелыми чтениями WB/Ozon;
- отдельный runtime-status интеграции, не смешанный с последней ручной
  проверкой;
- degraded health при свежем неуспешном source refresh;
- ограниченная автоматическая очистка старых директорий завершенных failed
  runs.
- адаптивная постраничная загрузка тяжелых 1С OData коллекций с immutable
  checkpoint и продолжением в новом `source_refresh_run`.

Не входит:

- подключение новых маркетплейсов;
- запись во внешние системы;
- изменение расчетной методики;
- автоматическое удаление snapshots успешных runs или snapshots, связанных с
  опубликованными отчетами.

# Runtime Guards

`source_refresh` обязан завершаться без внешних API-вызовов:

- `blocked_low_disk`, если на файловой системе `source_refresh_root` меньше
  `SHUMEYKO_SOURCE_REFRESH_MIN_FREE_GB`, default `8`;
- `blocked_active_refresh`, если `daily` стартует во время активного `full`, или
  если стартует второй активный run того же режима.

Blocked run сохраняется в `source_refresh_runs`, получает `finished_at` и
понятное safe-сообщение. Это нужно, чтобы systemd/health видели причину, а не
молчаливый пропуск.
CLI `run_source_refresh.py` завершает управляемые blocked statuses кодом `0`,
чтобы oneshot-unit не переходил в failed из-за штатного guard; health helper
остается источником alert-сигнала и возвращает `1` для blocked statuses.
Для неожиданных исключений `error_message` хранит тип ошибки и короткое
очищенное сообщение без длинных token/password/secret-подобных значений, чтобы
следующий incident был диагностируемым без чтения raw payloads или `.env`.
Новый report run сохраняется как draft и публикуется current только последним
шагом после source loads, финального статуса refresh и audit-записи; если после
сборки отчета случается ошибка, предыдущий published report остается текущим.

До внешних collectors для WB/Ozon `source_refresh` выполняет read-only
`GET .../$metadata` для обязательной 1С OData интеграции. Успешным считается
только `HTTP 200` с валидным EDMX XML и `EntityContainer`. При `404`, сетевой
ошибке или HTML вместо metadata run завершается `failed` до тяжелых загрузок
WB/Ozon. Результат сохраняется как обязательная коллекция
`onec_odata_metadata` и как безопасный `lastRuntimeCheck` интеграции без URL,
логина, пароля и response body.

Ручной `lastCheck` и автоматический `lastRuntimeCheck` — разные сигналы. UI
показывает более новый из них: успешная ручная проверка не должна скрывать
более поздний сбой scheduler, а последующее успешное runtime-чтение снимает
деградацию.

`GET /api/health` возвращает `status=degraded`, если последний завершенный
refresh имеет статус `failed`, `needs_configuration`, `blocked_low_disk` или
`blocked_active_refresh`. Активный новый run не скрывает предыдущий завершенный
сбой до своего успешного завершения.

# Provider Registry

Внутренний registry хранит для каждого базового провайдера:

- `providerBase`;
- label;
- read-only roles и default role;
- read-only check handler;
- `supportsMultiple`;
- `primaryProviderId`.

Первый registry содержит `wb_api` и `onec_readonly`. Существующие provider IDs и
payload `tenant_integrations` сохраняются совместимыми.

`GET /api/integrations` возвращает прежний `items` и новый `providers`.
Секреты, raw payloads и connection strings не возвращаются.

# Source Collectors

Текущий refresh использует `SourceCollector` contract:

- `sku_mapping`;
- `wb_product_cards`;
- `wb_finance_detail`;
- `wb_sales_report_list`;
- `onec_odata`.

После реализации `docs/specs/marketplace-1c-mapping-service.md` `sku_mapping`
берется из собственного сервиса сопоставления. Source refresh регулярно грузит
WB cards через read-only collector `wb_product_cards`, пересчитывает кандидатов
из read-only WB/Ozon/1С snapshots и проверяет свежесть current mapping view.
TXT/TSV/CSV upload остается только emergency fallback и импортом кандидатов без
записи в 1С, WB или Ozon.

План режимов:

- `daily`: mapping, WB product cards, WB finance, 1C OData;
- `weekly` и `full`: mapping, WB product cards, WB finance, WB report list,
  1C OData;
- `onec-only`: mapping, 1C OData.

Новые провайдеры можно сохранять и проверять read-only через registry, но они не
попадают в расчет без отдельного accepted spec для collector, lineage и формул.

## 1C OData pagination and resume

`Document_ОтчетКомиссионера` и `Document_РасходнаяНакладная` читаются
страницами по `5` заголовков с явным `$select`: идентификатор, дата, номер,
статус проведения, входящий номер/комментарий и документные суммы. Тяжелые
товарные табличные части в эти snapshots не входят; режим `header_only`
фиксируется в collection manifest и source-refresh collection lineage. Для
детальной Ozon-сверки отсутствие этих строк означает `needs_review`, а не ноль.
`Document_ПриходнаяНакладная` сохраняет необходимые финансовые табличные части
`Расходы` и `Запасы` и помечается как `financial_tables`. Вложенные регистры
используют меньшие collection-specific страницы, описанные ниже. При
`ReadTimeout` размер текущей страницы уменьшается до безопасного минимума;
каждый размер допускает исходный запрос и до трех повторов с паузами `2/5/15`
секунд. Live 1С возвращает `HTTP 500` на серверный фильтр по `Edm.DateTime`,
поэтому документы читаются только со стабильным `Posted eq true`, малыми
страницами и сортировкой `Date,Ref_Key`; ограничение отчетного периода по
`Date` выполняется при нормализации и фиксируется как
`local_document_date` в manifest.
В опубликованной 1С OData-модели регистры `Запасы`, `ЗапасыНаСкладах`,
`Продажи`, `ДоходыИРасходы` и взаиморасчеты возвращают верхнеуровневые записи
`Recorder/RecordSet`; поле `Period` находится внутри вложенного `RecordSet`.
Поэтому серверный `$filter=Period...` для них недопустим. Такие источники
читаются небольшими батчами со стабильной сортировкой по `Recorder`, а период
ограничивается при нормализации вложенных строк; режим
`nested_recordset_local` явно фиксируется в manifest. Размеры страниц
подбираются по фактическому весу recorder: `Продажи=2`, `Запасы` и
`ЗапасыНаСкладах=25`, `ДоходыИРасходы=50`, взаиморасчеты=`100`.

Каждая успешно прочитанная страница немедленно сохраняется отдельным raw JSON,
после чего атомарно обновляется collection manifest с хешем query contract,
хешами страниц, числом строк, фактическим page size и следующим OData cursor.
При сбое после одной или нескольких страниц коллекция получает
`partial_source` и сохраняет фактические `row_count/page_count`; недоступные
данные не заменяются нулем. После полного чтения рядом потоково собирается
обратносуместимый `<sample_id>.raw.json` для существующих loaders.
1С snapshot больше `25 MiB` не дублируется строками в PostgreSQL: raw files и
их hashes остаются authoritative, а collection payload получает
`rowPersistence.status=skipped_large_snapshot`. Перед долгим внешним чтением
текущая DB-транзакция завершается, чтобы idle PostgreSQL connection не
удерживался на время OData download.

Resume не изменяет каталог завершенного запуска. Новый run получает новый
`snapshot_set_id`, `resumed_from_run_id` и может использовать только
совместимый checkpoint того же клиента, 1С-контура, периода, коллекции и query
contract. Каждая переиспользуемая страница сначала проверяется по хешу и затем
копируется или hard-link-ится в новый snapshot. Поврежденный или несовместимый
checkpoint игнорируется, коллекция читается заново. Завершенные compatible
collection checkpoints переиспользуются без повторного запроса в 1С; у
аварийно завершенного run принимается последний атомарный `running` manifest,
а `max_pages` считается бюджетом новых страниц, поэтому следующий run реально
продвигает cursor. По умолчанию web/API и CLI
используют `resumeMode=auto`; `never` принудительно начинает чистый snapshot,
а staff может явно передать `resumeFromRunId`.

`commissioner_reports` является publication-required: его сбой допускает
staff draft, но блокирует публикацию и закрытие документной сверки.
`stock_movements` остается optional и дает предупреждение, если обязательный
`sales_register` и сверка себестоимости подтверждены. Поле `required`
сохраняет прежнюю совместимость, новое `publication_required` явно отделяет
барьер построения от барьера публикации.

# Staff Refresh Control UX

Для нового клиента нельзя зависеть от уже опубликованного отчета: у такого
клиента может еще не быть `report_run`, поэтому сервис сопоставления, импорт
кандидатов и первый `full` refresh должны быть доступны из staff-only раздела
`Интеграции`.

Требования:

- `consultant/admin` видит в модальном окне интеграций отдельный блок
  `Обновление данных`;
- блок показывает последний `source_refresh` выбранного клиента: статус, режим,
  период, safe-сообщение, новый report id и статусы коллекций без raw payloads,
  секретов и connection strings;
- staff может открыть сервис сопоставления, пересчитать кандидатов и
  импортировать TXT/TSV/CSV mapping WB ↔ 1C на уровне клиента через fallback
  endpoint; импорт сохраняется в `SHUMEYKO_SOURCE_REFRESH_MAPPING_DIR`, audit
  пишет только имя и размер файла;
- staff может запустить dry-run через `/api/clients/{client_id}/source-refresh`
  с `dry_run=true`, чтобы проверить конфигурацию без внешних WB/1C чтений;
- staff может запустить явный `full` refresh через тот же endpoint с
  `mode=full`; запуск использует encrypted tenant integrations и создает новый
  report run только если mandatory sources прошли;
- клиентская роль не видит эти controls и получает `403` на staff endpoints;
- если refresh уже идет, source refresh guard возвращает safe статус
  `blocked_active_refresh`, а UI показывает это как штатную занятость.

# Retention

`scripts/prune_source_refresh.py` по умолчанию работает как dry-run. При
`--apply` удаляются только старые direct child directories внутри
`data/source_refresh` или заданного `--source-root`.

Защищены:

- последние `daily-*` директории, default `3`;
- последние `full-*` директории, default `2`;
- snapshot ids published report runs из БД, если передан database URL;
- незавершенные refresh runs из БД.

Скрипт не трогает `.env`, `reports`, `data/web`, PostgreSQL и любые пути вне
`source_refresh_root`.

После завершения run со статусом `failed` сервис автоматически удаляет только
старые direct-child директории других завершенных failed runs того же tenant.
Текущий failed snapshot и последние
`SHUMEYKO_SOURCE_REFRESH_FAILED_SNAPSHOT_KEEP` failed snapshots сохраняются;
default `2`. Директории active runs, successful runs, published report
snapshots, symlinks и пути вне `source_refresh_root` не удаляются. Ошибка
cleanup не меняет статус refresh и не должна скрывать исходную ошибку.

# Acceptance Criteria

- Low-disk guard не вызывает WB/1C exporters.
- Недоступная или невалидная 1С `$metadata` не вызывает WB/Ozon exporters.
- Runtime-status 1С показывает более новый автоматический сбой отдельно от
  последней ручной проверки.
- `/api/health` показывает `degraded` при свежем завершенном failed refresh,
  в том числе пока следующий run еще active.
- Active full блокирует daily статусом `blocked_active_refresh`.
- Provider registry отдает WB/1C metadata и default roles.
- `/api/integrations` совместим по `items` и содержит `providers`.
- staff-only mapping service сохраняет решения и импорт кандидатов без
  публикации raw содержимого в API/audit.
- Source refresh проверяет mapping service, а отсутствие старой папки
  `data/onec_marketplace_mapping` не считается самостоятельным blocker.
- `/api/clients/{client_id}/source-refresh` staff-only запускает dry-run или
  `full` refresh и возвращает safe payload последнего run.
- UI раздела `Интеграции` содержит блок `Обновление данных` с переходом в
  сервис сопоставления, fallback upload mapping, dry-run, full refresh и
  статусом коллекций.
- `prune_source_refresh.py` dry-run ничего не удаляет.
- Автоочистка failed snapshots сохраняет минимум два последних failed runs и
  не выходит за direct children `source_refresh_root`.
- Non-SQLite SQLAlchemy engine использует `pool_pre_ping` и `pool_recycle`.
- Тесты, ruff, docs validators и no-secrets validators проходят.
- Таймаут тяжелой 1С страницы уменьшает batch без потери уже сохраненных
  страниц; следующий совместимый run продолжает с checkpoint без дублей.
- `commissioner_reports=partial_source/failed` блокирует публикацию, а
  optional `stock_movements` не превращается в ноль и не блокирует отчет при
  подтвержденной обязательной себестоимости.

# Rollout

1. Применить код и документацию.
2. Запустить локальные проверки.
3. Проверить live `/api/health`, `/api/integrations` 401 без авторизации,
   `/.env` 404.
4. Проверить `scripts/check_source_refresh_health.py --systemd`.
5. Включать или перезапускать daily timer только после проверки, что active full
   завершен и disk guard больше не блокирует нормальный refresh.

# Changelog

- 2026-07-10: added adaptive 1C OData batches, immutable per-page checkpoints,
  cross-run resume lineage and publication-required source semantics.
- 2026-07-10: added fail-fast 1C EDMX metadata guard, runtime integration
  status, degraded health and bounded failed-snapshot cleanup.
- 2026-07-08: switched mapping freshness/readiness to the project-owned
  marketplace/1C mapping service; file upload remains fallback candidate import.
- 2026-07-04: added staff refresh control UX/API for client-level mapping
  upload, dry-run readiness check and manual full refresh from integrations.
- 2026-06-24: accepted spec for source refresh hardening, provider registry,
  collector contract and retention CLI.
