---
title: "Индекс документации проекта"
doc_type: docs_index
domain: "marketplace-analytics"
audience: ["engineering", "consultant", "client"]
status: active
source_of_truth: false
updated_at: "2026-07-13"
---

# Индекс документации проекта

Этот файл помогает быстро понять, какой документ читать первым. Если документы
конфликтуют, порядок источников правды задан в `AGENTS.md`: accepted
implementation spec, затем общий MVP spec, затем клиентские документы и README.

# Главные источники правды

`source_of_truth` сохраняется для обратной совместимости. Машинный приоритет
задают `truth_scope` и `truth_priority`: документы сравниваются только внутри
одного scope, большее число имеет приоритет. Для каждого scope в manifest есть
ровно один документ с максимальным приоритетом.

- `AGENTS.md` — правила работы агента, безопасность, spec-first workflow и
  порядок разрешения конфликтов.
- `docs/product-concept-ai-report-analyst.md` — продуктовая рамка
  `AI-аналитик отчетов`: Шумейко является пилотным WB/1C контуром, а не
  названием всего продукта.
- `docs/specs/wb-unit-economics-excel-mvp-implementation.md` — accepted spec
  текущего Excel MVP.
- `docs/decisions/2026-07-10-tax-profiles-osno-profit.md` — accepted ADR по
  налоговым профилям, ОСНО, НДС к уплате и прибыли до НДФЛ.
- `docs/specs/marketplace-1c-mapping-service.md` — implemented spec собственного
  сервиса сопоставления WB/Ozon и 1С; это текущий источник правды для
  `sku_mapping`.
- `docs/specs/onec-marketplace-mapping-http-service.md` — superseded spec
  узкого read-only HTTP-сервиса 1С; теперь только candidate import/fallback.
- `docs/specs/onec-marketplace-mapping-client-extension.md` — superseded spec
  клиентского `.cfe` расширения; теперь только candidate import/fallback.
- `docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md` — accepted
  spec авторизованного web-кабинета, PostgreSQL-витрины и AI-аналитика.
- `docs/specs/wb-unit-economics-db-first-report-marts.md` — accepted spec
  DB-first публикации: БД как источник готового отчета, Excel/web/DOCX/PDF/CSV
  как экспорты.
- `docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md` —
  accepted spec hardening `source_refresh`, provider registry и retention CLI.
- `docs/specs/source-refresh-database-retention.md` — accepted spec пакетной
  ретенции raw snapshot rows PostgreSQL с защитой report lineage.
- `docs/specs/marketplace-unit-economics-ozon-integration.md` — accepted spec
  read-only Ozon Seller API, raw snapshots и общего marketplace-слоя WB/Ozon.
- `docs/specs/wb-unit-economics-ai-git-workflow.md` — accepted spec
  безопасного Git workflow для разработки с ИИ, локальных hooks и публикации.
- `docs/specs/wb-unit-economics-mvp.md` — продуктовая рамка пилота и будущих
  этапов.
- `docs/specs/wb-unit-economics-client-web-cabinet.md` — superseded draft,
  сохраненный как исторический предшественник accepted web-spec.
- `docs/generated/web-api.md` — route inventory, автоматически собранный из
  текущего FastAPI OpenAPI.
- `README.md` — локальная структура проекта, секреты, базовые команды.
- `config/README.md` — что можно хранить в non-secret конфигурации.

# Источники истины по scope

| Scope | Канонический документ | Приоритет |
| --- | --- | ---: |
| `project-governance` | `AGENTS.md` | 100 |
| `project-overview` | `README.md` | 100 |
| `configuration` | `config/README.md` | 100 |
| `product-scope` | `docs/specs/wb-unit-economics-mvp.md` | 100 |
| `excel-methodology` | `docs/specs/wb-unit-economics-excel-mvp-implementation.md` | 100 |
| `tax-methodology` | `docs/decisions/2026-07-10-tax-profiles-osno-profit.md` | 100 |
| `mapping` | `docs/specs/marketplace-1c-mapping-service.md` | 100 |
| `report-publication` | `docs/specs/wb-unit-economics-db-first-report-marts.md` | 100 |
| `web-cabinet` | `docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md` | 100 |
| `source-refresh` | `docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md` | 100 |
| `source-retention` | `docs/specs/source-refresh-database-retention.md` | 100 |
| `ozon` | `docs/specs/marketplace-unit-economics-ozon-integration.md` | 100 |
| `development-workflow` | `docs/specs/wb-unit-economics-ai-git-workflow.md` | 100 |

ADR `docs/decisions/2026-06-24-source-refresh-provider-registry-retention.md`
остается поддерживающим источником scope `source-refresh` с приоритетом 80.

`depends_on` задает только ациклический порядок реализации и совместимости.
Концептуальные обратные ссылки хранятся в `related_specs` и не участвуют в
порядке rollout.

# Что читать по контуру

| Контур | Главный документ | Статус | Когда читать |
| --- | --- | --- | --- |
| Product frame | `docs/product-concept-ai-report-analyst.md` | accepted | Уточнить, что Шумейко WB/1C является пилотом продукта `AI-аналитик отчетов`. |
| Excel MVP | `docs/specs/wb-unit-economics-excel-mvp-implementation.md` | accepted | Меняется методика, состав workbook, формулы, источники WB/1С или критерии приемки Excel. |
| Marketplace/1C mapping | `docs/specs/marketplace-1c-mapping-service.md` | implemented | Меняется сервис сопоставления WB/Ozon и 1С, статусы, решения оператора, candidate import или экспорт `sku_mapping`. |
| 1C marketplace mapping fallback | `docs/specs/onec-marketplace-mapping-client-extension.md` | superseded | Нужно понять старый путь импорта кандидатов из расширения `ИС_Маркетплейс`; не использовать как основной источник правды. |
| DB-first publication | `docs/specs/wb-unit-economics-db-first-report-marts.md` | accepted | Меняется источник готового отчета, публикация `report_run` или экспорт Excel/DOCX/PDF/CSV. |
| Web cabinet / AI | `docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md` | accepted | Меняется авторизованный кабинет, multi-client переключение, роли, API, AI-черновик, readiness или закрытый экспорт. |
| Source refresh | `docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md` | accepted | Меняется регулярная загрузка источников, provider registry, guards или retention raw snapshots. |
| Source refresh DB retention | `docs/specs/source-refresh-database-retention.md` | accepted | Меняются правила хранения raw snapshot rows PostgreSQL или процедура освобождения диска. |
| Ozon integration | `docs/specs/marketplace-unit-economics-ozon-integration.md` | accepted | Добавляется Ozon Seller API, Ozon raw snapshots, marketplace-разрез или смешанная WB/Ozon финмодель. |
| Month close pilot | `docs/specs/month-close-control-pilot.md` | draft | Нужно понять пилотный read-only контур закрытия месяца: онлайн-ОСВ, налоги, ЕНС, НДС, скрины и процессные подтверждения до CRM. |
| AI Git workflow | `docs/specs/wb-unit-economics-ai-git-workflow.md` | accepted | Меняется безопасная публикация AI-assisted изменений, GitHub CI, hooks, checks или commit/push workflow. |
| Client handoff | `docs/client-acceptance-package.md` | draft | Нужно собрать пакет приемки конкретного опубликованного `report_id` без статического «текущего» отчета. |

# Клиентский пакет

- `docs/client-acceptance-package.md` — шаблон и процедура сборки пакета
  приемки конкретного опубликованного `report_id`.
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
- `docs/runbooks/onec-marketplace-mapping-client-extension.md` — исторический
  fallback: установка `.cfe` расширения 1С для импорта кандидатов.
- `docs/runbooks/onec-marketplace-mapping-http-service.md` — исторический
  fallback: настройка HTTP-сервиса 1С и BSL-модуля.
- `docs/runbooks/report-generation.md` — сборка и проверка Excel MVP.
- `docs/runbooks/reconciliation-artifacts.md` — локальные артефакты для сверки
  WB и 1С.
- `docs/runbooks/power-bi-power-query.md` — путь от регулярного Excel/CSV к
  Power Query и Power BI поверх расчетных витрин.
- `docs/runbooks/web-cabinet-operations.md` — эксплуатация web-кабинета:
  пользователи, импорт report runs, AI, live checks, backup и monitor.
- `docs/runbooks/source-refresh-schedule.md` — active runbook для systemd
  timers, отдельного worker и staff incremental source refresh WB/1C.
- `docs/runbooks/ai-git-workflow.md` — безопасный цикл разработки с ИИ:
  локальные проверки, GitHub CI, коммит, push и pre-commit hook.

# Решения

- `docs/decisions/2026-07-10-tax-profiles-osno-profit.md` — действующее решение
  по налоговым профилям и клиентской семантике прибыли.
- `docs/decisions/2026-06-18-excel-mvp-methodology-decisions.md` — superseded
  решение с legacy-формулой `НДС 5/105 + УСН 1%`.
- `docs/decisions/2026-06-23-db-first-publication-baseline.md` — исторический
  снимок DB-first на 23.06.2026 и parity-решение `18179 vs 18820`.
- `docs/decisions/2026-06-24-source-refresh-provider-registry-retention.md` —
  решение по provider registry, blocked statuses и dry-run-first retention.
- `docs/changelogs/excel-mvp.md` — полная история изменений accepted Excel MVP,
  вынесенная из длинного implementation spec.

# Проверки документации

Запускать после изменения docs:

```bash
.venv/bin/python scripts/validate_docs_manifest.py
.venv/bin/python scripts/validate_llm_docs.py
.venv/bin/python scripts/validate_specs.py
.venv/bin/python scripts/validate_documentation_contracts.py
.venv/bin/python scripts/build_client_tz_docx.py --check
.venv/bin/python scripts/generate_web_api_reference.py --check
.venv/bin/python scripts/validate_no_secrets.py
```

Внешние URL проверяются отдельно и не входят в блокирующий набор локальных
проверок:

```bash
.venv/bin/python scripts/check_external_docs_links.py
```

Если менялись формулы, коннекторы или Excel builder, дополнительно запускать
релевантные тесты проекта.
