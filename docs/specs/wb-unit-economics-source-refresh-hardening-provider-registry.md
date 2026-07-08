---
spec_id: "wb-unit-economics-source-refresh-hardening-provider-registry"
title: "Shumeyko source refresh hardening and provider registry"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
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
updated_at: "2026-07-04"
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

Не входит:

- подключение новых маркетплейсов;
- запись во внешние системы;
- изменение расчетной методики;
- автоматическое удаление raw snapshots без явного `--apply`.

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
- `wb_finance_detail`;
- `wb_sales_report_list`;
- `onec_odata`.

До отдельного accepted spec на API-сопоставление из 1С `sku_mapping` остается
локальным файловым источником: консультант может загрузить актуальную
TXT/TSV/CSV выгрузку сопоставления WB ↔ 1C через staff-only web-кабинет, файл
сохраняется в `SHUMEYKO_SOURCE_REFRESH_MAPPING_DIR`, а refresh читает его как
read-only snapshot source без записи в 1С или WB.

План режимов:

- `daily`: mapping, WB finance, 1C OData;
- `weekly` и `full`: mapping, WB finance, WB report list, 1C OData;
- `onec-only`: mapping, 1C OData.

Новые провайдеры можно сохранять и проверять read-only через registry, но они не
попадают в расчет без отдельного accepted spec для collector, lineage и формул.

# Staff Refresh Control UX

Для нового клиента нельзя зависеть от уже опубликованного отчета: у такого
клиента может еще не быть `report_run`, поэтому mapping upload и первый `full`
refresh должны быть доступны из staff-only раздела `Интеграции`.

Требования:

- `consultant/admin` видит в модальном окне интеграций отдельный блок
  `Обновление данных`;
- блок показывает последний `source_refresh` выбранного клиента: статус, режим,
  период, safe-сообщение, новый report id и статусы коллекций без raw payloads,
  секретов и connection strings;
- staff может загрузить TXT/TSV/CSV mapping WB ↔ 1C на уровне клиента через
  `/api/clients/{client_id}/mapping-file`; файл сохраняется в
  `SHUMEYKO_SOURCE_REFRESH_MAPPING_DIR`, audit пишет только имя и размер файла;
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

# Acceptance Criteria

- Low-disk guard не вызывает WB/1C exporters.
- Active full блокирует daily статусом `blocked_active_refresh`.
- Provider registry отдает WB/1C metadata и default roles.
- `/api/integrations` совместим по `items` и содержит `providers`.
- `/api/clients/{client_id}/mapping-file` staff-only сохраняет mapping-файл без
  публикации raw содержимого в API/audit.
- `/api/clients/{client_id}/source-refresh` staff-only запускает dry-run или
  `full` refresh и возвращает safe payload последнего run.
- UI раздела `Интеграции` содержит блок `Обновление данных` с upload mapping,
  dry-run, full refresh и статусом коллекций.
- `prune_source_refresh.py` dry-run ничего не удаляет.
- Non-SQLite SQLAlchemy engine использует `pool_pre_ping` и `pool_recycle`.
- Тесты, ruff, docs validators и no-secrets validators проходят.

# Rollout

1. Применить код и документацию.
2. Запустить локальные проверки.
3. Проверить live `/api/health`, `/api/integrations` 401 без авторизации,
   `/.env` 404.
4. Проверить `scripts/check_source_refresh_health.py --systemd`.
5. Включать или перезапускать daily timer только после проверки, что active full
   завершен и disk guard больше не блокирует нормальный refresh.

# Changelog

- 2026-07-04: added staff refresh control UX/API for client-level mapping
  upload, dry-run readiness check and manual full refresh from integrations.
- 2026-06-24: accepted spec for source refresh hardening, provider registry,
  collector contract and retention CLI.
