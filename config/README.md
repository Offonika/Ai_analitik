---
title: "Config"
doc_type: config_guide
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: active
source_of_truth: true
truth_scope: configuration
truth_priority: 100
updated_at: "2026-07-15"
---

# Config

Здесь хранятся и документируются настройки пилота без секретов:

- список кабинетов;
- период отчета;
- правила маппинга товаров;
- явная связка `WB_ACCOUNT_*` с организациями 1С;
- версия методики расчета.

API-ключи Wildberries здесь не хранить. Для локальных Excel/export сценариев
используется только runtime `.env` вне Git. Для web-кабинета ключи клиента
вводятся в tenant-level разделе `Интеграции` и сохраняются только как
encrypted secret при настроенном `SHUMEYKO_INTEGRATION_SECRET_KEY`; plaintext
не должен попадать в документы, HTML, JSON или Git.

Доступ к 1С OData здесь тоже не хранить. Для локального read-only подключения
Excel/export используются переменные:

- `ONEC_ODATA_BASE_URL`;
- `ONEC_ODATA_USERNAME`;
- `ONEC_ODATA_PASSWORD`;
- `ONEC_ODATA_VERIFY_SSL`;
- `ONEC_ODATA_TIMEOUT_SECONDS`.

Для web-кабинета 1С read-only подключение вводится в tenant-level разделе
`Интеграции`. Проверка подключения читает только OData `$metadata` и не
возвращает URL с учетными данными или пароль в API/audit.

Состав опубликованных объектов 1С фиксируется в документах и должен быть
минимальным для Excel MVP.

Для первого Excel MVP автоматическая связка кабинета WB и организации 1С может
быть только provisional. Перед приемкой отчета ее нужно подтвердить с заказчиком
или вынести в отдельный non-secret config.

GUID-настройки сверки `1С ОПиУ` можно вынести в
`config/onec_opiu_accounts.json` по шаблону
`config/onec_opiu_accounts.example.json`. В нем хранятся только non-secret
идентификаторы счетов выручки, себестоимости, НДС, РВБ-услуг и структурной
единицы. Если файл не задан, Excel помечает ОПиУ-сверку как `pilot defaults`.

Быстрая staff-пересборка управляется non-secret параметрами:

- `SHUMEYKO_SOURCE_REFRESH_INCREMENTAL_ENABLED=false` — feature flag; включать
  только после миграции и shadow parity с последним `full`;
- `SHUMEYKO_SOURCE_REFRESH_INCREMENTAL_WINDOW_DAYS=28` — календарное окно WB,
  которое incremental загружает и атомарно заменяет в daily facts.

Режим также требует `SHUMEYKO_MARKETPLACE_DAILY_FACTS_ENABLED=true` и
`SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true`.

Каталог web-отчетов управляется non-secret настройкой
`SHUMEYKO_ENABLED_REPORT_KINDS`. Безопасный default —
`marketplace_unit_economics`. Staff-only advisory rollout выполняется поэтапно:
сначала добавляется `month_close_control`, после проверки — `tax_load`.
Откат удаляет новый вид из списка и не удаляет report runs, snapshots или audit.

Production rollout задается версионированными systemd drop-ins:

- `/etc/shumeiko-web-prod.env` и `/etc/shumeiko-web-test.env` всегда раздельны;
- production использует `SHUMEYKO_RUNTIME_ENVIRONMENT=production`, test —
  `SHUMEYKO_RUNTIME_ENVIRONMENT=test`;
- test задает отдельные `SHUMEYKO_DATABASE_URL`,
  `SHUMEYKO_SESSION_COOKIE_NAME`, `SHUMEYKO_ALLOWED_EXPORT_ROOT` и
  `SHUMEYKO_SOURCE_REFRESH_ROOT`, запрещает client login и по умолчанию
  отключает `SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED`;
- `deploy/systemd/shumeiko-web.service.d/accounting-report-kinds.conf` и
  одноименный worker drop-in — безопасный initial rollout: новые бухгалтерские
  виды установлены, но выключены; включение выполняется добавлением
  `month_close_control`, затем `tax_load` после контрольных сверок;
- `deploy/systemd/shumeiko-web.service.d/incremental-refresh.conf` — показывает
  staff incremental в web и включает обязательные DB-first/daily-facts flags;
- `deploy/systemd/shumeiko-source-refresh-worker@.service.d/incremental-refresh.conf`
  — разрешает тот же режим отдельному worker;
- `deploy/systemd/shumeiko-source-refresh-worker@.service.d/marketplace-facts.conf`
  — сохраняет обязательные daily facts и file-authoritative marketplace contour.

Drop-ins не содержат токены или URL подключений. Удаление обоих
`incremental-refresh.conf` является feature-flag rollback; созданные
draft/snapshots при этом сохраняются.

AI runtime настраивается только через runtime env:

- `SHUMEYKO_OPENAI_MODEL` — модель Responses API;
- `SHUMEYKO_OPENAI_TIMEOUT_SECONDS=60` — общий timeout одного запроса;
- `SHUMEYKO_CHATKIT_ENABLED=false` — опциональный custom-server UI transport;
- `SHUMEYKO_CHATKIT_DOMAIN_KEY` — публичный domain key ChatKit web component.

OpenAI API key остается секретом и в этот каталог не попадает. ChatKit включают
только вместе с domain key после staff acceptance; без feature flag штатным
transport остается `/messages/stream`. Attachments и внешние actions отключены.
