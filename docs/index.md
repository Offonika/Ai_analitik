---
title: "Индекс документации проекта"
doc_type: docs_index
domain: "marketplace-analytics"
audience: ["engineering", "consultant", "client"]
status: active
source_of_truth: false
updated_at: "2026-07-04"
---

# Индекс документации проекта

Этот файл помогает быстро понять, какой документ читать первым. Если документы
конфликтуют, порядок источников правды задан в `AGENTS.md`: accepted
implementation spec, затем общий MVP spec, затем клиентские документы и README.

# Главные источники правды

- `AGENTS.md` — правила работы агента, безопасность, spec-first workflow и
  порядок разрешения конфликтов.
- `docs/product-concept-ai-report-analyst.md` — продуктовая рамка
  `AI-аналитик отчетов`: Шумейко является пилотным WB/1C контуром, а не
  названием всего продукта.
- `docs/specs/wb-unit-economics-excel-mvp-implementation.md` — accepted spec
  текущего Excel MVP.
- `docs/specs/onec-marketplace-mapping-http-service.md` — accepted spec узкого
  read-only HTTP-сервиса 1С для сопоставления WB и 1С из расширения
  `ИС_Маркетплейс`.
- `docs/specs/onec-marketplace-mapping-client-extension.md` — accepted spec
  клиентского `.cfe` расширения, которое пакует read-only HTTP-сервис для
  установки в базы клиентов.
- `docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md` — accepted
  spec авторизованного web-кабинета, PostgreSQL-витрины и AI-аналитика.
- `docs/specs/wb-unit-economics-db-first-report-marts.md` — accepted spec
  DB-first публикации: БД как источник готового отчета, Excel/web/DOCX/PDF/CSV
  как экспорты.
- `docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md` —
  accepted spec hardening `source_refresh`, provider registry и retention CLI.
- `docs/specs/marketplace-unit-economics-ozon-integration.md` — accepted spec
  read-only Ozon Seller API, raw snapshots и общего marketplace-слоя WB/Ozon.
- `docs/specs/wb-unit-economics-ai-git-workflow.md` — accepted spec
  безопасного Git workflow для разработки с ИИ, локальных hooks и публикации.
- `docs/specs/wb-unit-economics-mvp.md` — продуктовая рамка пилота и будущих
  этапов.
- `docs/specs/wb-unit-economics-client-web-cabinet.md` — draft spec первого
  клиентского web-кабинета поверх принятой Excel-методики.
- `README.md` — локальная структура проекта, секреты, базовые команды.
- `config/README.md` — что можно хранить в non-secret конфигурации.

# Что читать по контуру

| Контур | Главный документ | Статус | Когда читать |
| --- | --- | --- | --- |
| Product frame | `docs/product-concept-ai-report-analyst.md` | accepted | Уточнить, что Шумейко WB/1C является пилотом продукта `AI-аналитик отчетов`. |
| Excel MVP | `docs/specs/wb-unit-economics-excel-mvp-implementation.md` | accepted | Меняется методика, состав workbook, формулы, источники WB/1С или критерии приемки Excel. |
| 1C marketplace mapping | `docs/specs/onec-marketplace-mapping-client-extension.md` | accepted | Нужно подключить сопоставление WB и 1С из расширения `ИС_Маркетплейс` через устанавливаемое read-only `.cfe` расширение. |
| DB-first publication | `docs/specs/wb-unit-economics-db-first-report-marts.md` | accepted | Меняется источник готового отчета, публикация `report_run` или экспорт Excel/DOCX/PDF/CSV. |
| Web cabinet / AI | `docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md` | accepted | Меняется авторизованный кабинет, multi-client переключение, роли, API, AI-черновик, readiness или закрытый экспорт. |
| Source refresh | `docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md` | accepted | Меняется регулярная загрузка источников, provider registry, guards или retention raw snapshots. |
| Ozon integration | `docs/specs/marketplace-unit-economics-ozon-integration.md` | accepted | Добавляется Ozon Seller API, Ozon raw snapshots, marketplace-разрез или смешанная WB/Ozon финмодель. |
| AI Git workflow | `docs/specs/wb-unit-economics-ai-git-workflow.md` | accepted | Меняется безопасная публикация AI-assisted изменений, hooks, Git checks или commit/push workflow. |
| Client handoff | `docs/client-acceptance-package.md` | draft | Нужно объяснить клиенту текущий опубликованный baseline, ограничения и что именно принимается. |

# Клиентский пакет

- `docs/client-acceptance-package.md` — короткий пакет приемки текущего
  опубликованного baseline как клиентской ревизии `report_run`.
- `docs/client-value-proposition-ai-assistant.md` — выгода AI-ассистента,
  экономия времени, подписочная логика и design-partner скидка для клиента.
- `docs/client-scope.md` — короткий scope для согласования с заказчиком.
- `docs/client-tz.md` — клиентское ТЗ в Markdown.
- `docs/shumeyko-partners-wb-unit-economics-client-tz.docx` — DOCX-версия
  клиентского ТЗ.
- `docs/client-methodology.md` — методика расчета простым языком.
- `docs/calculation-formulas.md` — формулы расчета показателей, сверок и
  статусов.
- `docs/power-bi-wb-model-reference.md` — безопасная выжимка из ранней Power
  BI-модели WB: структура, страницы, идеи формул и ограничения переноса.
- `docs/wb-financial-report-power-bi-measures-review.md` — сверка текущего
  расчета финансового отчета WB с ранними Power BI-мерами и список улучшений.
- `docs/client-analytical-report-draft.md` — шаблон AI-черновика аналитической
  записки к Excel-отчету для проверки консультантом.

# Доступы и операционные инструкции

- `docs/onec-access-instruction.md` — инструкция по read-only доступу к 1С.
- `docs/runbooks/onec-marketplace-mapping-client-extension.md` — установка и
  проверка клиентского `.cfe` расширения 1С для экспорта сопоставления WB и 1С.
- `docs/runbooks/onec-marketplace-mapping-http-service.md` — настройка
  HTTP-сервиса 1С и BSL-модуля, который входит в клиентское расширение.
- `docs/runbooks/report-generation.md` — сборка и проверка Excel MVP.
- `docs/runbooks/reconciliation-artifacts.md` — локальные артефакты для сверки
  WB и 1С.
- `docs/runbooks/power-bi-power-query.md` — путь от регулярного Excel/CSV к
  Power Query и Power BI поверх расчетных витрин.
- `docs/runbooks/web-cabinet-operations.md` — эксплуатация web-кабинета:
  пользователи, импорт report runs, AI, live checks, backup и monitor.
- `docs/runbooks/source-refresh-schedule.md` — установка systemd timers для
  daily/weekly source refresh WB/1C.
- `docs/runbooks/ai-git-workflow.md` — безопасный цикл разработки с ИИ:
  проверки, коммит, push и локальный pre-commit hook.

# Решения

- `docs/decisions/2026-06-18-excel-mvp-methodology-decisions.md` — ключевые
  решения текущего Excel MVP, вынесенные из длинного implementation spec.
- `docs/decisions/2026-06-23-db-first-publication-baseline.md` — текущий
  DB-first publication baseline, parity-решение `18179 vs 18820` и source
  refresh readiness blocker.
- `docs/decisions/2026-06-24-source-refresh-provider-registry-retention.md` —
  решение по provider registry, blocked statuses и dry-run-first retention.
- `docs/changelogs/excel-mvp.md` — полная история изменений accepted Excel MVP,
  вынесенная из длинного implementation spec.

# Проверки документации

Запускать после изменения docs:

```bash
.venv/bin/python scripts/validate_docs_manifest.py
.venv/bin/python scripts/validate_llm_docs.py
.venv/bin/python scripts/validate_specs.py docs/specs/wb-unit-economics-mvp.md
.venv/bin/python scripts/validate_specs.py docs/specs/wb-unit-economics-excel-mvp-implementation.md
.venv/bin/python scripts/validate_specs.py docs/specs/onec-marketplace-mapping-client-extension.md
.venv/bin/python scripts/validate_specs.py docs/specs/onec-marketplace-mapping-http-service.md
.venv/bin/python scripts/validate_specs.py docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md
.venv/bin/python scripts/validate_specs.py docs/specs/wb-unit-economics-db-first-report-marts.md
.venv/bin/python scripts/validate_specs.py docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md
.venv/bin/python scripts/validate_specs.py docs/specs/wb-unit-economics-ai-git-workflow.md
.venv/bin/python scripts/validate_no_secrets.py
```

Если менялись формулы, коннекторы или Excel builder, дополнительно запускать
релевантные тесты проекта.
