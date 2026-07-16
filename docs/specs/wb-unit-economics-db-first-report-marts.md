---
spec_id: "workspace-shumeyko-partners-wb-unit-economics-db-first-report-marts"
title: "Шумейко WB/1C: DB-first report marts"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
truth_scope: report-publication
truth_priority: 100
related_code: [src/wb_unit_economics/report_marts.py, src/wb_unit_economics/report_exports.py, src/wb_unit_economics/web/models.py, src/wb_unit_economics/web/repository.py, scripts/rebuild_report_from_sources.py, scripts/export_report_artifacts.py]
related_tests: [tests/test_report_marts.py, tests/test_db_first_publication.py, tests/test_web_app.py, tests/test_source_refresh.py]
contracts: [unit_economics_report, report_marts, report_artifacts]
depends_on: [workspace-shumeyko-partners-wb-unit-economics-excel-mvp-implementation]
related_specs: [workspace-shumeyko-partners-wb-unit-economics-ai-web-cabinet-implementation]
supersedes: [legacy_excel_import_as_regular_build_path]
rollout_required: true
updated_at: "2026-07-16"
---

# Implementation Status

Статус остается `accepted`. DB-first marts, exports и публикационный контур
реализованы и покрыты целевыми тестами, но полный production rollout и все
acceptance criteria не перепроверяются в рамках документационной
синхронизации. Для `implemented` нужна отдельная доказательная матрица.

# Goal

Перевести штатную публикацию отчета Шумейко WB/1C на DB-first контур:

```text
read-only sources/snapshots
  -> deterministic calculation
  -> DB report marts
  -> Excel/web/DOCX/PDF/HTML/CSV/BI exports
```

Опубликованная расчетная БД является единственным источником готового отчета.
Excel, сайт, DOCX/PDF, HTML, CSV и Power Query являются экспортами из одного
`report_id`. Excel-import остается только legacy recovery path.

# Scope

Входит:

- контракт `ReportMarts`, который строится из `UnitEconomicsReport` без чтения
  workbook;
- перенос `lostSales` в общий deterministic слой, включая остатки 1С и
  человекочитаемые названия складов;
- сохранение `unitRows`, `lostSales`, `reconciliationMonthly`,
  `documentReconciliation`, KPI/readiness payload в БД;
- публикационный статус report run: `draft`, `published`, `failed`;
- единственный `current` published report на tenant;
- artifact registry: `report_id`, `artifact_type`, `path`, `hash`,
  `created_at`, `status`;
- экспорт Excel/DOCX/PDF/HTML/CSV из `report_id`;
- обновленный `SourceRefreshService`: `daily` не публикует клиентский отчет,
  `weekly/full` в DB-first режиме публикуют только после validation и export;
- единый effective tax-profile input для DB-first calculation и readiness:
  профиль текущего read-only снимка настроек организации 1С, затем действующее
  аудируемое ручное исключение как fallback, затем явный `missing`, без
  наследования опубликованного отчета и без отдельного ручного подтверждения
  уже загруженных настроек 1С;
- production health без секретов: тип БД, schema version, latest published
  report, latest source refresh.

Не входит:

- изменение формул юнит-экономики;
- write-интеграции в WB, 1С, банк, CRM, Telegram, email или Bitrix;
- публикация raw snapshots, токенов, `.env` или необработанных клиентских
  выгрузок через клиентское API;
- произвольный SQL/BI-конструктор для клиента.

# Data Layers

## Source Snapshots

Read-only WB, 1С и mapping lineage сохраняются как raw/source слой. Этот слой
нужен для воспроизводимости, но не доступен клиентскому API.

## Calculation / Report Marts

`UnitEconomicsReport` остается расчетным контрактом методики. `ReportMarts`
преобразует его в готовые витрины:

- `unitRows`;
- `lostSales`;
- `reconciliationMonthly`;
- `documentReconciliation`;
- `monthly`, `expenses`, `returns`;
- `readiness` и `meta`.

Web не считает прибыль на лету. Web читает только сохраненные строки и summary
payload из БД.

## Web Publication

Новый отчет создается как `draft`. После mart validation и успешного artifact
export он одной операцией становится `published/current` для tenant. Старый
`current` сохраняется до успешной публикации новой ревизии.

## Artifacts

Артефакты строятся из сохраненного `report_id` и регистрируются с hash/status.
Поля `source_workbook` и `source_workbook_path` остаются только для legacy
compatibility и Excel download fallback.

# Public Interfaces

Основной rebuild:

```bash
.venv/bin/python scripts/rebuild_report_from_sources.py \
  --tenant-id shumeyko \
  --report-id <report_id> \
  --report-period-start <YYYY-MM-DD> \
  --report-period-end <YYYY-MM-DD> \
  --export-all
```

Экспорт из опубликованной БД:

```bash
.venv/bin/python scripts/export_report_artifacts.py \
  --report-id <report_id> \
  --excel --docx --pdf --html --csv
```

Legacy recovery import:

```bash
.venv/bin/python scripts/import_web_report_from_excel.py \
  --workbook reports/shumeyko_wb_excel_mvp.xlsx \
  --report-id legacy_recovery_YYYY_MM_DD
```

# DB Rules

- Production/staging используют Postgres через `SHUMEYKO_DATABASE_URL`.
- SQLite разрешен только для local/dev/test fallback.
- Health/smoke показывает тип БД и предупреждает, если live-контур смотрит на
  SQLite.
- DB-first schema version фиксируется в `schema_migrations`.
- `report_runs` хранит выбранный `report_period` отдельно от
  `source_coverage_start` / `source_coverage_end`; связанный
  `source_refresh_run` остается lineage/fallback, но web summary не должен
  зависеть от него для отображения coverage опубликованного отчета.
- `create_all` может создать пустую локальную схему, но DB-first поля и
  publication semantics должны проходить через версионированную миграционную
  запись.

# Acceptance Criteria

- `ReportMarts` строится без чтения Excel.
- `lostSales` подтягивает остатки 1С и названия складов.
- `missing_mapping`, `ambiguous_mapping`, `missing_cost`, `partial_source` не
  становятся reliable.
- Web summary/rows/lostSales читаются из БД.
- Web summary показывает `reportPeriod`, `sourceCoverage`,
  `sourceCoverageStart`, `sourceCoverageEnd` из опубликованного `report_run`
  даже если отчет опубликован вручную без нового `source_refresh_run`.
- Excel export `reports/shumeyko_wb_excel_mvp.xlsx` строится из сохраненного
  `report_id`.
- Клиентский Markdown/DOCX/PDF/HTML строится через единый
  `ClientReportModel` из `report_full_payload` того же `report_id`; workbook и
  локальные каталоги `latest` не читаются.
- Artifact registry пишет path/hash/status без raw secrets.
- `daily` source refresh не публикует клиентский report.
- `weekly/full` source refresh публикуют только после validation/export.
- Ошибка новой ревизии не снимает старый `current`.

# Test Plan

Unit:

- `tests/test_report_marts.py`;
- `tests/test_db_first_publication.py`;
- KPI parity с текущей методикой.

Integration:

- temp SQLite: sources -> calculation -> marts -> DB -> exports -> web payload;
- Postgres migration smoke;
- web API без workbook import;
- publication rollback.

Regression:

- `.venv/bin/python -m pytest`;
- `.venv/bin/python -m ruff check src tests scripts`;
- `.venv/bin/python scripts/validate_no_secrets.py`;
- `.venv/bin/python scripts/validate_docs_manifest.py`;
- `.venv/bin/python scripts/validate_llm_docs.py`;
- live smoke: `/api/health = 200`, закрытые endpoints без авторизации = `401`,
  raw/public secret paths = `404`.

# Rollout

1. Создать DB-first spec и schema migration.
2. Реализовать `ReportMarts` builder и сохранить web payload shape.
3. Собрать новый DB-first report под временным `report_id`.
4. Сравнить с текущим Excel/web: KPI, строки, top lost sales, остатки 1С,
   document reconciliation, monthly reconciliation.
5. Включить `SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true` для штатного
   `source refresh`.
6. Оставить Excel-import fallback на один релиз как rollback.
7. Обновить runbooks: источник правды - опубликованная расчетная БД, Excel -
   экспорт.

# Historical Rollout Snapshot

На 2026-06-23 был зафиксирован рабочий DB-first baseline:

- report snapshot: `excel_mvp_2026_03_01_2026_06_17`;
- `unitRows`: 18179;
- `lostSales`: 776;
- artifact registry: 9 ready records.

Parity-решение и источник старого ориентира `18820` зафиксированы в
`docs/decisions/2026-06-23-db-first-publication-baseline.md`.

Оставшиеся эксплуатационные blockers для регулярной live-загрузки sources:

- runtime-ready WB/1C integrations должны быть сохранены в `tenant_integrations`;
- `source_refresh` может завершаться как `failed` при required source/schema
  errors;
- `blocked_low_disk` и `blocked_active_refresh` останавливают запуск до внешних
  API-вызовов;
- systemd timers должны быть активны после rollout.

Эти blockers не отменяли снимок DB-first baseline и не блокировали ручную
публикацию из уже проверенных локальных snapshots, но должны быть закрыты перед
масштабированием регулярных интеграций.

# Changelog

- 2026-06-23: accepted DB-first report marts spec.
- 2026-06-23: recorded published/current DB-first baseline and source refresh
  readiness blocker.
- 2026-06-24: clarified source refresh operational blockers after hardening
  plan: credentials, failed/schema errors, low disk, active run conflicts and
  timer state.
- 2026-06-24: added persistent source coverage to `report_runs` so published
  DB-first reports keep `report_period` and `source_coverage` separate without
  relying on the latest refresh run.
- 2026-07-16: switched the client analytical document from Excel parsing to a
  single DB-first report model and clarified automatic 1C tax-settings input.
