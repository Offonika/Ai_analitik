---
title: "Индекс документации проекта"
doc_type: docs_index
domain: "marketplace-analytics"
audience: ["engineering", "consultant", "client"]
status: active
source_of_truth: false
updated_at: "2026-07-18"
---

# Индекс документации проекта

Этот файл помогает быстро понять, какой документ читать первым. Если документы
конфликтуют, порядок источников правды задан в `AGENTS.md`: accepted
implementation spec, затем общий MVP spec, затем клиентские документы и README.

# Источники истины и AI-маршрут

`source_of_truth` сохраняется для обратной совместимости. Машинный приоритет
задают `truth_scope` и `truth_priority`: документы сравниваются только внутри
одного scope, большее число имеет приоритет. Для каждого scope в manifest есть
ровно один документ с максимальным приоритетом.

- `CLAUDE.md` — короткая автозагружаемая точка входа Claude Code;
- `docs/product-concept-ai-report-analyst.md` — supporting product concept;
- `docs/generated/web-api.md` — generated inventory текущего FastAPI OpenAPI;
- `docs/generated/ai-routing.jsonl` — generated одно-строчная AI-карта.

ADR `docs/decisions/2026-06-24-source-refresh-provider-registry-retention.md`
остается поддерживающим источником scope `source-refresh` с приоритетом 80.

`depends_on` задает только ациклический порядок реализации и совместимости.
Концептуальные обратные ссылки хранятся в `related_specs` и не участвуют в
порядке rollout.

Карта scope → код и тесты хранится в frontmatter самого спека: поля
`related_code` и `related_tests`. Существование перечисленных путей проверяет
`scripts/validate_specs.py`; при переносе или добавлении модулей эти списки
обновляются в том же изменении.

Таблица ниже генерируется из `docs/manifest.yml`. Для компактного AI-поиска
использовать `.venv/bin/python scripts/docs_route.py --query "<задача>"`.

<!-- BEGIN GENERATED AI ROUTING -->
| Scope | Канонический документ | Приоритет | Статус | Когда читать |
| --- | --- | ---: | --- | --- |
| `accounting-reports-smart-process` | `docs/specs/accounting-reports-smart-process-onepage.md` | 100 | implemented | Меняется бухгалтерский Канбан, workflow tasks, SLA, delivery/follow-up, feature flag или закрытие к зарплате. |
| `client-analytical-report` | `docs/specs/client-analytical-report-implementation.md` | 100 | accepted | Меняется клиентский аналитический документ, executive summary, evidence, формат DOCX/PDF/HTML или narrative по report_id. |
| `configuration` | `config/README.md` | 100 | active | Меняется non-secret конфигурация клиента, методики, налогового профиля или account mapping. |
| `development-workflow` | `docs/specs/wb-unit-economics-ai-git-workflow.md` | 100 | accepted | Меняется AI-навигация по документации, docs metadata, CI, hooks, проверки, commit/push или безопасная публикация изменений. |
| `excel-methodology` | `docs/specs/wb-unit-economics-excel-mvp-implementation.md` | 100 | accepted | Меняются источники WB/1С, формулы, data contracts, состав workbook или критерии приемки Excel MVP. |
| `logistics-cost-analysis` | `docs/specs/wb-logistics-cost-analysis-implementation.md` | 100 | accepted | Меняется анализ логистики WB, data gate, цепочки заказов, рейтинги SKU, рекомендации или логистические витрины. |
| `mapping` | `docs/specs/marketplace-1c-mapping-service.md` | 100 | implemented | Меняется сопоставление товаров WB/Ozon и 1С, candidate import, решения оператора или экспорт sku_mapping. |
| `month-close-control` | `docs/specs/month-close-control-report-implementation.md` | 100 | accepted | Меняется контроль закрытия месяца, ОСВ/evidence, календарь, проверки 1С, web или Excel этого report_kind. |
| `multi-report-cabinet` | `docs/specs/multi-report-cabinet-implementation.md` | 100 | accepted | Меняются report_kind, registry отчетов, асинхронная генерация, shared report contract или advisory/enforced checks. |
| `ozon` | `docs/specs/marketplace-unit-economics-ozon-integration.md` | 100 | accepted | Меняются Ozon Seller API, finance/accrual sources, Ozon mart, расходы, mapping или Ozon preview. |
| `product-scope` | `docs/specs/wb-unit-economics-mvp.md` | 100 | accepted | Меняется продуктовый scope пилота, роли, этапы, общий результат или границы AI-аналитика отчетов. |
| `project-governance` | `AGENTS.md` | 100 | active | Перед изменением файлов, разрешением конфликтов документации или работой с секретами и внешними интеграциями. |
| `project-overview` | `README.md` | 100 | active | Нужен обзор репозитория, локальный setup, структура каталогов или базовые команды пилота. |
| `report-publication` | `docs/specs/wb-unit-economics-db-first-report-marts.md` | 100 | accepted | Меняются report marts, публикация report_id, lineage, current report или экспортные форматы. |
| `runtime-contours` | `docs/specs/web-cabinet-runtime-contours.md` | 100 | accepted | Меняются production/test контуры, runtime paths, systemd units, releases, promotion или rollback. |
| `source-refresh` | `docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md` | 100 | accepted | Меняется загрузка WB/1С/Ozon, provider registry, refresh guards, collectors, resume или raw snapshot lifecycle. |
| `source-retention` | `docs/specs/source-refresh-database-retention.md` | 100 | accepted | Меняются raw-row retention, очистка старых черновиков отчетов, backup verification, VACUUM или освобождение диска. |
| `tax-load-report` | `docs/specs/tax-load-report-implementation.md` | 100 | accepted | Меняется отчет налоговой нагрузки, формула ФНС, УСН Д−Р, tax profile, evidence v7, web или Excel этого report_kind. |
| `tax-methodology` | `docs/decisions/2026-07-10-tax-profiles-osno-profit.md` | 100 | accepted | Меняются налоговые профили, ОСНО, входящий/исходящий НДС, НДС к уплате или прибыль до налогов. |
| `web-cabinet` | `docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md` | 100 | accepted | Меняется авторизованный кабинет, роли, multi-client доступ, API, AI tools, readiness или закрытый экспорт. |
<!-- END GENERATED AI ROUTING -->

Supporting, draft и superseded документы не входят в таблицу. Их можно найти
явно флагами `--include-supporting --include-history`.

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
- `docs/client-analytical-report-draft.md` — superseded Excel-first шаблон;
  сохранён как исторический ориентир.

# Исторические материалы

- `docs/power-bi-wb-model-reference.md` — superseded-reference ранней Power
  BI-модели; сохранён только как история до перехода на сервис.
- `docs/wb-financial-report-power-bi-measures-review.md` — superseded-анализ
  ранней Power BI-модели; сохранён только как история.

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
  production/test, пользователи, импорт report runs, AI, backup и monitor.
- `docs/runbooks/accounting-workflow-operations.md` — безопасное включение,
  dry-run, расписание, проверка evidence и rollback бухгалтерского
  смарт-процесса.
- `docs/runbooks/source-refresh-schedule.md` — active runbook для systemd
  timers, отдельного worker и staff incremental source refresh WB/1C.
- `docs/runbooks/ai-git-workflow.md` — безопасный цикл разработки с ИИ:
  компактный docs route, локальные проверки, GitHub CI, коммит и push.
- `docs/runbooks/wb-logistics-v4-continuation.md` — последнее записанное
  состояние WB-логистики по средам, evidence и безопасный test-rollout v5;
  фактическое состояние нужно повторно проверить перед operational-выводом.

# Решения

- `docs/decisions/2026-07-10-tax-profiles-osno-profit.md` — действующее решение
  по налоговым профилям и клиентской семантике прибыли.
- `docs/decisions/2026-07-14-accounting-reports-accountant-questions.md` —
  active-реестр: налоговый профиль и формула ФНС уже зафиксированы, а оставшиеся
  вопросы ограничивают подтвержденные статусы, enforced-проверки и клиентскую
  публикацию, но не accepted staff-only advisory v1.
- `docs/decisions/2026-06-18-excel-mvp-methodology-decisions.md` — superseded
  решение с legacy-формулой `НДС 5/105 + УСН 1%`.
- `docs/decisions/2026-06-23-db-first-publication-baseline.md` — исторический
  снимок DB-first на 23.06.2026 и parity-решение `18179 vs 18820`.
- `docs/decisions/2026-06-24-source-refresh-provider-registry-retention.md` —
  решение по provider registry, blocked statuses и dry-run-first retention.
- `docs/changelogs/excel-mvp.md` — полная история изменений accepted Excel MVP,
  вынесенная из длинного implementation spec.
- `docs/changelogs/web-cabinet.md` — полная история изменений accepted
  web-cabinet implementation spec.
- `docs/changelogs/ozon-integration.md` — полная история изменений accepted
  Ozon integration spec.

# Проверки документации

Запускать после изменения docs:

```bash
.venv/bin/python scripts/validate_docs_manifest.py
.venv/bin/python scripts/validate_llm_docs.py
.venv/bin/python scripts/docs_route.py --check-generated
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
