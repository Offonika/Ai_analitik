---
title: "Config"
doc_type: config_guide
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: active
source_of_truth: true
truth_scope: configuration
truth_priority: 100
updated_at: "2026-07-13"
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
