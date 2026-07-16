---
spec_id: "workspace-shumeyko-client-analytical-report-implementation"
title: "Клиентский аналитический отчёт WB/1С"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "consultant", "client"]
source_of_truth: true
truth_scope: client-analytical-report
truth_priority: 100
related_code: [src/wb_unit_economics/client_report.py, src/wb_unit_economics/document_exports.py, src/wb_unit_economics/report_exports.py, src/wb_unit_economics/web/app.py, scripts/build_client_analytical_report.py]
related_tests: [tests/test_client_report.py, tests/test_web_app.py]
contracts: [unit_economics_report, report_marts, client_analytical_report]
depends_on: [workspace-shumeyko-partners-wb-unit-economics-db-first-report-marts]
related_specs: [workspace-shumeyko-partners-wb-unit-economics-ai-web-cabinet-implementation]
supersedes: [docs/client-analytical-report-draft.md]
rollout_required: true
updated_at: "2026-07-16"
---

# Goal

Сформировать короткий, проверяемый и пригодный для передачи клиенту
аналитический отчёт по юнит-экономике WB. Один сохранённый `report_id` является
источником всех фактов, таблиц, выводов и ограничений документа.

```text
saved report_id
  -> report_full_payload
  -> ClientReportModel
  -> one deterministic Markdown
  -> DOCX / PDF / HTML
```

Excel является параллельным экспортом из того же `report_id`, а не входом для
аналитического документа.

# Audience And Decision

Основная аудитория — собственник, руководитель и консультант, которым нужно за
несколько минут понять:

- итог периода и готовность данных;
- какие кабинеты и товары формируют прибыль или убыток;
- какие расходы, возвраты и остатки требуют разбора;
- какие действия подтверждаются данными, а какие остаются сценариями.

# Scope

Входит:

- единая DB-first модель клиентского отчёта;
- Markdown как детерминированный reader-facing источник DOCX/PDF/HTML;
- executive summary, KPI, помесячная динамика, кабинеты, расходы, убыточные
  товары, возвраты, упущенные продажи, качество данных, сверка с 1С, налоговый
  блок, действия, открытые вопросы и ограничения;
- фирменный и нейтральный DOCX;
- PDF только через проверенную конвертацию готового DOCX;
- artifact hash и регистрация report-scoped файлов;
- staff draft при наличии финансовых blockers и клиентский gate через
  существующий readiness/publication контур.

Не входит:

- новые формулы юнит-экономики;
- чтение Excel или каталогов `latest` для подстановки фактов;
- прогнозирование отсутствующих периодов;
- автоматическое изменение цен, закупок, рекламы, остатков или данных 1С;
- обещание роста прибыли от одной рекомендации;
- AI-генерация чисел, причин или финансовых фактов.

# Source And Lineage Rules

- `repository.report_full_payload(db, report)` является единственным входом.
- `meta.reportId` обязателен; генерация без него завершается ошибкой.
- Период, coverage, методология, readiness, tax context и все строки относятся
  к одному immutable report run.
- Локальные raw snapshots, Excel workbook и «последняя» выгрузка не читаются.
- Один Markdown рендерится во все reader-facing форматы; DOCX хранит hash этого
  Markdown в свойствах документа.
- Generated artifacts остаются вне Git и доступны только через защищённый
  report-scoped API.

# Reader-Facing Structure

Порядок разделов:

1. короткий заголовок;
2. видимый `Executive Summary — краткий вывод`;
3. параметры отчёта и идентификатор `report_id`;
4. основные KPI;
5. динамика по фактически доступным месяцам;
6. сравнение кабинетов;
7. структура расходов WB и топ убыточных товаров;
8. возвраты и потенциально упущенные продажи;
9. качество данных и сверка с 1С;
10. налоговые настройки 1С;
11. действия;
12. открытые вопросы;
13. ограничения и допущения.

В DOCX используются таблицы для точных сумм и аудита. Встроенные графики не
входят в первую версию: динамика визуализируется в web/Excel, а документ должен
оставаться воспроизводимым без отдельного графического пайплайна.

# Metric Semantics

- Клиентское название результата до налогового слоя —
  `Управленческая прибыль WB`.
- `Прибыль до НДФЛ` показывается только когда применён налоговый слой из
  сохранённого report run.
- `Чистая прибыль` не используется.
- Нулевое отсутствующее значение не подставляется; выводится `Не рассчитано`.
- Кабинетные и товарные разрезы агрегируются только из `unitRows` текущего
  report run.
- Упущенные продажи показываются только при
  `lostSalesCoverage.calculated=true` и только за фактическое окно источника.
- Причина возврата и драйвер убытка не придумываются при отсутствии поля.

# Tax Profile Rule

- Организация, система налогообложения и ставки автоматически берутся из
  read-only настроек организации 1С и сохраняются в lineage report run.
- Отдельное ручное подтверждение налогового режима для клиентского документа не
  требуется.
- Если настройки 1С не загружены или не применены к выбранному `report_id`,
  налоговые KPI остаются `null`; документ показывает Управленческую прибыль WB
  до налогового слоя и предлагает обновить настройки из 1С.
- Аудируемое ручное исключение может оставаться техническим fallback принятой
  налоговой методики, но клиентский документ не просит вручную подтверждать
  уже загруженные настройки 1С.

# Recommendation Rules

- Каждое действие связано с рассчитанным фактом: missing cost, mapping, loss
  rows, returns, expenses или lost sales coverage.
- Изменение цены, скидки, закупки или продвижения формулируется как сценарий для
  отдельного расчёта, а не как обещание результата.
- Причины возвратов требуют отдельного read-only источника, если они не входят
  в report payload.
- AI может стилистически доработать отдельный staff-only client draft, но
  базовый документ всегда формируется без AI и остаётся полностью
  воспроизводимым.

# Readiness And Access

- Consultant/admin может сформировать внутренний документ для разбора draft.
- Клиентская роль не может сформировать или скачать рекомендации при наличии
  финансового publication blocker.
- Статус `ready` и причины ограничений выводятся из текущего report payload.
- Staff-only draft checks не включаются в клиентский текст.
- Markdown, DOCX и PDF регистрируются как report artifacts с hash и размером.

# Acceptance Criteria

- Генератор не принимает workbook path и не читает Excel.
- В документе виден точный `report_id`, период, coverage и версия методики.
- Executive Summary расположен сразу после заголовка.
- DOCX содержит KPI, кабинеты, расходы, убыточные товары, возвраты, lost sales,
  качество данных, налоговый блок, действия и ограничения.
- Налоговый блок прямо сообщает, что настройки взяты из 1С и отдельное ручное
  подтверждение не требуется.
- При отсутствующих настройках 1С нет налоговых нулей и нет текста
  `Подтвердить налоговый профиль`.
- В документе нет термина `чистая прибыль` для управленческого результата WB.
- Markdown и DOCX имеют одинаковый нормализованный текст; DOCX содержит hash
  исходного Markdown.
- HTML строится из того же Markdown и экранирует клиентские значения.
- PDF failure не создаёт пустой или stale файл и возвращает явный статус.
- Web endpoint генерирует документ из `report_full_payload` и регистрирует
  артефакты.

# Test Plan

Unit:

- структура и порядок разделов;
- налоговый профиль из 1С и missing-tax поведение;
- агрегация кабинетов, расходов, losses, returns и lost sales;
- денежное, процентное и количественное форматирование;
- escaping таблиц и HTML.

Artifact:

- Markdown/DOCX normalized-token parity;
- `source_sha256` в DOCX;
- DOCX open smoke;
- PDF conversion smoke при наличии LibreOffice.

Integration:

- authenticated analytical-report endpoint;
- DB-first payload передаётся генератору без workbook path;
- tenant/report isolation;
- artifact registry;
- client financial blocker gate.

Regression:

- `.venv/bin/python -m pytest tests/test_client_report.py tests/test_report_exports.py tests/test_web_app.py`;
- `.venv/bin/python -m ruff check src tests scripts`;
- документационные validators из `AGENTS.md`.

# Rollout And Rollback

1. Собрать новый документ для временного report run.
2. Сверить KPI, кабинеты, потери, налоговый блок и coverage с web/Excel.
3. Проверить DOCX и PDF визуально.
4. Переключить protected analytical-report endpoint на DB-first builder.
5. Сохранить Excel как независимый export и rollback-источник только для
   скачивания, но не для генерации текста.
6. При ошибке вернуть endpoint на предыдущую release-версию; уже опубликованный
   current report run не менять.

# Changelog

- 2026-07-16: accepted DB-first client analytical report v1; tax settings are
  read automatically from 1C without a separate manual-confirmation step.
