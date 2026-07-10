---
spec_id: "workspace-shumeyko-partners-wb-unit-economics-ai-web-cabinet-implementation"
title: "AI-аналитик отчетов: Shumeyko v2 web-кабинет"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
related_code: [src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/ai.py, src/wb_unit_economics/web/models.py, src/wb_unit_economics/web/repository.py, src/wb_unit_economics/web/refresh.py, sql/web_cabinet_schema.sql, scripts/import_web_report_from_excel.py, scripts/manage_web_users.py]
related_tests: [tests/test_web_app.py]
contracts: [wb_api_snapshot, onec_unf_cost_snapshot, sku_mapping, unit_economics_report, ai_analysis_summary]
depends_on: [docs/specs/wb-unit-economics-excel-mvp-implementation.md, docs/specs/marketplace-1c-mapping-service.md]
supersedes: [docs/specs/wb-unit-economics-client-web-cabinet.md]
rollout_required: true
updated_at: "2026-07-10"
---

# Goal

Реализовать production-рамку пилота продукта `AI-аналитик отчетов` на
`shumeiko.offonika.ru`: авторизация, tenant boundary, хранение расчетных витрин в
PostgreSQL, управляемый Excel export и AI-аналитик отчетов поверх уже
рассчитанных данных.

`Shumeyko v2` остается техническим именем пилотного WB/1C контура. Продуктовое
имя для повторного использования и упаковки: `AI-аналитик отчетов`.

Кабинет заменяет публичную статическую JSON/Excel-витрину. HTML-оболочка может
быть доступна без входа, но реальные цифры, Excel-файлы и AI-ответы доступны
только через авторизованный API.

# Scope

Входит:

- backend API на FastAPI;
- PostgreSQL-схема для консалтинговой компании, клиентов, клиентских юрлиц,
  WB-кабинетов, пользователей, report runs, строк отчета, audit и AI-чата;
- импорт текущего Excel MVP в первый `report_run`;
- email+password auth с HttpOnly session cookie и Argon2 password hash;
- роли `client`, `consultant`, `admin`;
- переключение клиента для consultant/admin в рамках доступов пользователя;
- server-side user management: создать пользователя, сбросить пароль,
  отключить доступ, посмотреть роли;
- API для списка отчетов, summary, строк, карточки SKU и Excel export;
- API для истории расчетов, freshness, повторного импорта Excel MVP и
  управленческой записки;
- web-фильтр `Месяц 1С` для строк отчета: недельная строка относится к месяцу
  фактического закрытия недели (`week_end`, воскресенье). Неделя
  `30.03–05.04` относится к апрелю, а `27.04–03.05` — к маю; кабинет не
  подменяет фактическую дату закрытия серединой недели или последним днем
  месяца;
- completeness check WB Finance требует raw coverage с понедельника первой
  недели, закрывающейся внутри периода; строки входят в отчет только при
  `report_period_start <= week_end <= report_period_end`;
- computed `report readiness score` в `summary` и `freshness`, чтобы
  consultant/admin видел, можно ли отправлять отчет клиенту, что требует
  проверки и что блокирует отправку;
- lightweight authenticated UI shell без отдельного frontend-сборщика:
  `/` и `/cabinet` отдают login/report shell, `/ai` и `/integrations`
  остаются совместимыми deep-link shell для открытия соответствующего виджета
  поверх отчета, `/static/*` отдает локальные CSS/JS assets, а все данные
  отчета загружаются только через защищенные `/api/*`;
- формирование фирменного клиентского аналитического отчета из Excel MVP в
  Markdown, DOCX и PDF, если на сервере доступен PDF-конвертер;
- AI-аналитик отчетов через OpenAI Responses API и серверные read-only tools;
- read-only live checks для 1С/WB как отдельные инструменты с аудитом и
  выключателем;
- staff-only AI-driven 1С auto-refresh: read-only дозагрузка нужных 1С OData
  коллекций, пересборка workbook и создание нового `report_run` без изменения
  текущего отчета;
- backup PostgreSQL, health monitor и audit-view для consultant/admin;
- явный запрет публичной раздачи JSON/Excel artifacts.

Не входит:

- запись в WB, 1С, Bitrix24, Telegram, email, банк или CRM;
- изменение себестоимости, маппинга, карточек, цен, остатков или документов;
- самостоятельные финансовые, налоговые, юридические или закупочные решения;
- загрузка raw snapshots, токенов или generated client reports в Git;
- произвольный SQL/BI-конструктор для клиента.

# Architecture

```text
Consulting firm / user access
  -> client data workspace (tenant boundary)
  -> client companies + WB cabinets
  -> WB/1C read-only snapshots
  -> deterministic calculation layer
  -> unit_economics_report / Excel MVP
  -> PostgreSQL report marts
  -> FastAPI auth API
  -> Astro client shell
  -> AI report analyst tools over report marts
```

Основной источник пользовательского UI — расчетная витрина. AI-аналитик отчетов
не получает секреты, raw payloads или прямой доступ к базе. AI вызывает только
whitelisted server-side tools, которые применяют tenant boundary и пишут audit
events.

Tenant остается границей безопасности и хранения расчетных данных. Бизнес-слой
поверх tenant описывает, какой консалтинговой компании принадлежит клиентский
контур, какие юрлица/организации 1С входят в клиента и какие WB-кабинеты
участвуют в расчете. WB-кабинет не является tenant: это измерение и фильтр
внутри клиентского контура, иначе общий отчет клиента с несколькими кабинетами
и юрлицами распадается на несвязанные витрины.

# Data Model

Минимальная PostgreSQL-схема:

- `consulting_firms`: консалтинговые компании или оператор продукта, которые
  ведут несколько клиентов;
- `tenants`: изолированный клиентский контур данных; в v2.11 сохраняется как
  основной security boundary и может быть связан с одним `client`;
- `clients`: бизнес-профиль клиента консалтинговой компании: `firm_id`,
  `tenant_id`, display name, status, default report settings;
- `client_companies`: юрлица/ИП клиента и организации 1С, включая
  человекочитаемое имя, safe external key/reference и статус активности;
- `wb_cabinets`: WB-кабинеты клиента, включая display name, safe cabinet key,
  optional `client_company_id`, linked `tenant_integrations.provider`,
  connection role and active flag;
- `users`: учетные записи без tenant-данных;
- `user_tenant_access`: роль пользователя в tenant;
- `sessions`: хэши сессионных токенов и срок жизни;
- `report_runs`: период, дата расчета, статус, методика, source workbook;
- `report_unit_rows`: строки клиентской витрины товаров;
- `report_lost_sales_rows`: управленческая оценка упущенных продаж;
- `report_reconciliation_monthly`: помесячная сверка WB и 1С/ОПиУ;
- `source_loads`: сведения об источниках и snapshot lineage;
- `tenant_integrations`: tenant-level статусы WB/1С подключений, masked
  `secret_hint`, `secret_hash`, encrypted `secretCiphertext` в
  `config_payload` при включенном `SHUMEYKO_INTEGRATION_SECRET_KEY`,
  last-check metadata и timestamps; для WB-кабинета и 1С базы связь с
  бизнес-сущностями хранится через safe metadata, а не через secret;
- `live_check_cache`: кеш read-only проверок 1С/WB с TTL и статусом
  `disabled`, `needs_configuration`, `needs_review` или `ok`;
- `data_refresh_jobs`: staff-only job дозагрузки 1С и пересборки отчета:
  `tenant_id`, `source_report_run_id`, `new_report_run_id`,
  `requested_by_user_id`, optional `thread_id`, `status`, `reason`,
  safe `collections`, `snapshot_dir`, `workbook_path`, `error_message`,
  `started_at`, `finished_at`, `created_at`, `updated_at`;
- `audit_events`: входы, просмотры, exports, AI tools, live checks;
- `ai_threads`, `ai_messages`, `ai_tool_calls`: чат и трассировка AI.
- `ai_events`: безопасная UI-лента работы AI-аналитика: статус, начало и
  завершение tool call, evidence-карточки, fallback и финальный статус.
- `ai_client_drafts`: staff-only ревизии клиентского черновика по report run:
  `tenant_id`, `report_run_id`, optional `thread_id`, `author_user_id`,
  `revision`, `status`, `source`, `content`, `instruction`, safe `evidence`,
  `limitations`, `created_at`, `updated_at`.

Plaintext-секреты внешних систем не хранятся в таблицах. Для tenant
integrations допустим только encrypted ciphertext, полученный runtime-ключом
`SHUMEYKO_INTEGRATION_SECRET_KEY`, плюс hash/hint/status. Если runtime-ключ не
настроен, секрет сохраняется только hash-only и не может использоваться для
live-check до повторного ввода.

В v2.11 обратная совместимость сохраняется: существующий `tenant` Shumeyko
становится одним `client` внутри одной `consulting_firm`, а текущие текстовые
значения `cabinet` и `organization` в report rows остаются видимыми fallback.
После миграции новые расчеты должны также заполнять стабильные
`client_id`, `client_company_id` и `wb_cabinet_id`, чтобы переключение клиента,
юрлица и WB-кабинета не зависело от текста в строках отчета.

`report readiness score` не хранится отдельной таблицей в v2.5. Он вычисляется
из `report_runs`, `report_unit_rows`, `source_loads` и, только для ролей
`consultant/admin`, статуса latest `ai_client_drafts`.

UI shell не хранит и не встраивает report data в HTML/JS. Он показывает login
без авторизации, затем через same-origin API получает `/api/me`, `/api/reports`,
`summary`, `freshness`, review rows и staff-only `client-draft`, если роль
пользователя это допускает.

## Multi-Client Access Model

Иерархия доступа:

```text
consulting_firm
  -> client / tenant
     -> client_companies
     -> wb_cabinets
     -> report_runs
```

Роли:

- `admin`: управляет пользователями, клиентами, интеграциями, импортом и audit
  в рамках своей consulting firm или разрешенных tenants;
- `consultant`: видит назначенных клиентов, переключает клиентские витрины,
  проверяет readiness, интеграции, AI-черновики и source refresh;
- `client`: видит только свои опубликованные отчеты и разрешенные срезы без
  staff-only данных.

Правила:

- один консультант может иметь доступ к нескольким клиентам одной
  консалтинговой компании;
- один клиент может иметь несколько юрлиц/организаций 1С и несколько
  WB-кабинетов;
- WB-кабинет и организация 1С являются фильтрами внутри клиентской витрины, а
  не самостоятельными security tenants;
- клиентская роль не может переключиться на другого клиента, даже если знает
  `client_id`, `tenant_id`, `report_id`, `wb_cabinet_id` или URL;
- AI threads, client drafts, integrations, source refresh and audit events
  всегда привязаны к выбранному клиенту/tenant и не переиспользуются между
  клиентами.

# Public API

Фактический список методов и путей не дублируется вручную. Он генерируется из
текущего OpenAPI в `docs/generated/web-api.md` командой
`python scripts/generate_web_api_reference.py`; `--check` выявляет рассинхрон.

Этот spec закрепляет бизнес-права независимо от конкретного route inventory:

- health, login shell и статические UI assets доступны без report data;
- все клиентские, отчетные, integration, mapping и AI операции требуют сессию;
- роль `client` читает только разрешенный client/report scope и не видит
  staff draft, audit, секреты, raw paths или integration configuration;
- роли `consultant/admin` управляют клиентскими workspace, mapping decisions,
  client drafts и read-only refresh в пределах разрешенных tenants;
- только `admin` управляет пользователями и системным audit;
- live checks и source refresh читают внешние системы, но не записывают в WB,
  Ozon или 1С;
- каждый запрос с `client_id`, `tenant_id` или `report_id` повторно проверяет
  принадлежность объекта доступному пользователю контуру.

`GET /api/me` returns the user's available client workspaces. If the user has
access to multiple clients, the UI must require an explicit selected client
before loading report data. If the user has exactly one client, the UI may
auto-select it.

`GET /api/clients` returns only clients available to the user. Each item
includes `clientId`, `tenantId`, `firmId`, display name, role, current report id,
readiness status and safe counts of active WB/1С connections. It must not return
secrets, raw source paths or clients outside the user's access scope.

`POST /api/clients` is available only to `consultant/admin` users. It creates a
new client workspace with a separate `tenant_id`/`client_id`, optional initial
1C organizations and WB cabinets, assigns the creator to that tenant with a
staff role, writes an audit event and returns the same safe client payload used
by `GET /api/clients`. Role `client` must receive 403 and no public
registration is introduced.

`GET /api/clients/{client_id}/reports` returns report runs only for that client.
The endpoint must reject a mismatched `client_id`/`tenant_id`/`report_id`
combination even if the user has access to another client.

`GET /api/reports/{id}/summary` and `GET /api/reports/{id}/freshness` include:

```json
{
  "readiness": {
    "status": "ready | needs_review | partial_period | partial_source | source_coverage_gap | failed",
    "score": 0,
    "label": "Готов к отправке | Нужна проверка | Неполный период | Неполный источник | Разрыв покрытия | Ошибка подготовки",
    "blockingReasons": [],
    "reviewReasons": [],
    "nextAction": "...",
    "checkedBy": "system"
  }
}
```

Readiness v1 rules:

- no report rows or failed report/source status -> `failed`;
- source coverage that does not cover selected `report_period` ->
  `source_coverage_gap`;
- incomplete source load or partial row source -> `partial_source`;
- incomplete or preliminary report period -> `partial_period`;
- missing 1C cost, mapping issue, more than 20% problem rows, or non-ready
  client draft -> `needs_review`;
- no blockers/review reasons and score at least 85 -> `ready`;
- the client role can see readiness, but must not see or infer staff-only
  client draft state; draft-related reasons are included only for
  `consultant/admin`.

Финансовые причины всегда являются блокирующими: смешение методов P&L,
расхождение `profit` и `profitBeforeTax` до НДФЛ, неподтвержденный входящий НДС,
незакрытая себестоимость, неуспешный обязательный source lineage, отсутствие
подтверждения нулевых хранения/приемки, незакрытая независимая месячная или
документная сверка. При наличии такой причины UI показывает точный заголовок
`Финансовая проверка не пройдена`, а клиентский AI не формирует рекомендации и
возвращает HTTP 409.

UI readiness behavior:

- unauthenticated visitor sees only the login shell and no report data;
- after login, UI shows a client switcher when the user has more than one
  available client;
- `consultant/admin` can create a new client workspace from the topbar; after
  creation the UI switches to that client and prompts staff to add integrations
  before report data exists;
- selecting a client reloads only that client's reports, integrations, readiness
  and AI context;
- if a user has exactly one client, UI may load the latest available report for
  that client automatically;
- topbar includes quick filters for `Кабинет WB`, `Дата начала` and
  `Дата конца`, synchronized with the detailed row filters for cabinet,
  `period_start` and `period_end`;
- topbar does not expose an `Отчет` selector; selecting a client loads the
  current available report slice automatically;
- report meta, source freshness and client hierarchy are not repeated as a
  separate middle-screen block; the topbar and readiness strip are the canonical
  context, and mapping service entry appears only in the main next-action area;
- topbar action `Клиентский вывод` opens the staff/client output state as a
  modal widget over the current report instead of scrolling to a lower report
  section;
- topbar action `Интеграции` opens read-only WB/1C tenant connections as a
  modal widget over the current report instead of scrolling to a lower report
  section or navigating away; the compatible `/integrations` deep link opens
  the same widget after the current client context loads;
- topbar action `AI` opens the AI analyst as a modal widget over the current
  report instead of scrolling to a lower report section or navigating away; the
  compatible `/ai` deep link opens the same widget after the current client
  report loads;
- readiness panel shows label, score, next action, blocking reasons and review
  reasons;
- when the next action is `Обновить mapping WB ↔ 1C`, the readiness panel opens
  the staff-only mapping service first: consultant sees marketplace rows,
  1C candidates, accept/reject/revoke/exclude actions and history. A
  TXT/TSV/CSV file upload remains visible as bulk accepted import for already
  mapped rows, while skipped/conflict rows stay in the manual queue; after
  mapping decisions or import, the UI starts from the returned `autoRefresh`
  result: if a new report run exists, it opens that recalculated vitrine
  automatically; if refresh is disabled, busy or failed, it shows a safe status
  instead of asking the user to run refresh manually;
- if readiness includes `partial_period`, the next-action copy explicitly tells
  the consultant to either state the preliminary period to the client or wait
  for the complete period, even when the primary action is mapping refresh;
- ambiguous controls use the shared `data-tooltip` UI hint pattern, visible on
  hover and keyboard focus, without exposing raw data or secrets;
- preflight panel spans the report width and shows compact quality diagnostics
  as a horizontal row above the task kanban; the kanban columns for consultant
  work are `Исправить сейчас`, `В работе у аналитика` and
  `Готово к отправке`; diagnostics keep an `OK` progress summary and compact
  metrics for rows `ОК`, missing 1C cost, mapping issues, incomplete sources
  and partial period; every open task card includes a short explanation and a
  direct action to the relevant row filter, period controls, integrations
  widget, client-output widget or WB ↔ 1С reconciliation tab; document
  reconciliation issues add a dedicated `onec_reconciliation_review` task;
  consultant/admin may also mark a task card as `Проверено` in the browser UI,
  which moves it to `Готово к отправке` as a local workflow acknowledgement for
  the current report but does not mutate source data, calculation facts,
  readiness score or report status;
- preflight deciphering opens a modal `Расшифровки проблем` widget with tabs
  for review rows, source refresh diagnostics, missing 1C cost, mapping issues
  and losses, so consultants can switch contexts without scrolling through
  stacked tables; source-load reasons open the source diagnostics tab instead
  of the generic integrations widget and show safe statuses such as
  `blocked_low_disk`, period, refresh mode and source collection counts;
- lower detail tables are grouped into one `Детализации` workspace where
  `Юнит-экономика` is the first/default tab, followed by the prominent
  `Сверка документов`, liquidity and lost sales;
  switching tabs does not reload report data; the reconciliation tab loads
  rows from `/api/reports/{id}/document-reconciliation`, shows metrics for
  documents, OK rows, rows needing review, quantity delta, amount delta and
  missing 1С fact, and supports filters for search, status, period start/end,
  cabinet, organization, document type and `Только расхождения`; the
  same tab first shows financial reconciliation from
  `/api/reports/{id}/financial-document-reconciliation`: KPI pairs `WB`, `1С`
  and `Дельта 1С − WB` for revenue with VAT and penalties, followed by rows
  with the WB report, actual 1С documents, amounts, status and explanation;
  `Статья` filters the rows by revenue with VAT or penalties. The WB side uses
  report rows whose weekly closing date (`week + 6 days`) falls inside the
  selected period, while the 1С side uses actual register `Period` or
  incoming-invoice `Date` inside that period.
  A matching 1С document outside the selected dates is not silently included:
  it is named in the row and receives status `Документ 1С вне периода`. The
  signed delta is always `1С − WB`, tolerance for `Сходится` is 1 ruble, and
  unavailable source facts remain missing instead of being coerced to source
  zero;
  the existing generic document-load reconciliation remains below the
  financial block for quantity, payout and completeness controls; the
  `Юнит-экономика` tab keeps filters for search, status, period start/end,
  month, cabinet, organization, scheme and loss class before loading rows
  through `/api/reports/{id}/rows`, and shows revenue, profit, margin and unit
  profit for every report row;
- unit-economics filters auto-apply on change/input; the UI does not require a
  separate `Применить` action, while `Сбросить` clears the slice explicitly;
- `Показатели` is recalculated from the filtered `rows` response, so
  cabinet/date/detail filters change the displayed money KPIs together with the
  table; the strip also shows management-estimated `Упущенные продажи` from
  `report_lost_sales_rows` as lost revenue for the current report run/cabinet,
  and lays out the cards as two rows with revenue, profit, margin, lost sales,
  sales, net sales, returns, return rate, revenue per sale and loss-row count;
- summary exposes `lostSalesCoverage`, `taxContext` and calendar month metadata.
  A missing tax profile or incomplete stock-history is rendered as a visible
  `Не рассчитано` state with the exact coverage/source reason; it is never
  rendered as a confirmed zero and the analytics block is not removed;
- `taxContext.calculated` remains `false` when any report organization has no
  profile for part of the report period, when `vatDeductionMode=unknown`, or
  when the confirmed tax object is not supported by the current methodology;
  `readiness.blockingReasons[]` exposes `tax_profile_unconfirmed` in these
  cases;
- when WB limits daily stock history to its last three calendar months,
  `lostSalesCoverage` keeps the full requested report period and the actual
  provider window separately; the uncovered earlier days remain explicit;
- `lostSales[].lostContributionMargin` is the canonical preliminary estimate
  before tax. `lostProfit` remains a compatibility alias. Aggregate lost-sales
  KPI is nullable unless every selected cabinet has complete daily stock
  coverage for the report period;
- `Аналитика` appears after `Показатели` and before the readiness command
  board; v1 renders embedded dependency-free visualizations from
  `summary.monthly`, `summary.expenses`, `summary.lostSales`,
  `summary.liquidityRows` and `summary.kpis`: grouped column charts for money
  dynamics, a P&L-style unit economics table, horizontal bars for top losses
  and return columns with return-rate context;
- `Аналитика` also works as a review navigator: a compact
  `Что разобрать первым` row prioritizes missing 1C cost, mapping, WB ↔ 1C
  reconciliation, loss rows, lost sales and returns, and every card/chart click
  opens the relevant drilldown, detail tab or unit-economics preset without
  mutating source data;
- the unit-economics tab exposes quick row presets `Все`, `Убыточные`,
  `Без себестоимости`, `Mapping`, `Возвраты` and `К проверке`; `preset=returns`
  filters rows with returns or positive return rate;
- analytics charts are read-only and show the current report run as a whole;
  dashboard-wide filterable analytics can be added later through a dedicated
  read-only analytics endpoint or filtered rows aggregation;
- return months are ordered by machine-readable `monthStart`; an incomplete
  month stays last, shows `daysElapsed/daysInMonth`, and is not presented as a
  like-for-like comparison with complete months;
- VAT reconciliation preserves signed amounts and shows charges, reversals and
  net separately. It includes cabinet/organization and source evidence status,
  uses a full-width semantic table, and never labels VAT as deductible while
  `taxContext.vatDeductionMode` is `unknown`;
- period filters use row `week` when available and fall back to the row month or
  ISO WB report date for imported rows without a week date; for rows with a
  week the month/date filter uses the closing Sunday (`week + 6 days`) so a
  cross-month week is not assigned by its Monday start. Partial date metadata
  does not silently zero the money KPIs;
- the cabinet filter defaults to all active WB cabinets of the selected client;
  choosing a cabinet changes all KPI/detail blocks to that slice without
  changing tenant security scope;
- the organization filter defaults to all active client companies/1C
  organizations of the selected client;
- unit-economics table must stay inside its panel and scroll horizontally on
  narrow screens instead of clipping the right-side columns;
- AI-аналитик отображается как всплывающий виджет поверх отчета: быстрые
  вопросы, история сообщений, линия событий read-only tools и источник ответа
  `openai`/`fallback`;
- `consultant/admin` видит staff-only раздел `Интеграции` для tenant-level
  WB API и 1С read-only подключений; ключи не относятся к профилю пользователя;
- `consultant/admin` may see client-draft status in a modal staff-only widget;
- `client` role does not see client-draft status or draft-related readiness
  reasons.

# AI Boundaries

AI tools may:

- summarize period KPIs;
- search SKU rows by product, article, barcode or `nmId`;
- explain loss drivers from calculated rows;
- list data-quality issues;
- compare available report periods;
- draft a management report from computed facts;
- request a read-only 1C/WB live check when enabled.
- for `consultant/admin` only, call `refresh_onec_and_rebuild_report` when
  `SHUMEYKO_AUTO_REFRESH_ENABLED=true` and the question is about missing 1С
  себестоимость, маппинг, сверку, ОПиУ, партии, услуги WB/УПД or остатки.

AI tools must not:

- write to WB, 1С or other external systems;
- invent missing cost, mapping or return reasons;
- hide `partial_source`, `missing_cost`, `missing_mapping`,
  `ambiguous_mapping` or `needs_review`;
- produce a final financial/legal/accounting decision;
- expose raw identifiers, tokens, `.env`, webhook URLs or SQL errors.

## Staff-Only AI-Driven 1С Auto-Refresh

AI tool `refresh_onec_and_rebuild_report` is available only to roles
`consultant` and `admin`. Role `client` cannot trigger it through API, AI chat,
streaming or UI; the safe response is that consultant review is required.

The tool is disabled by default. It may create a job only when
`SHUMEYKO_AUTO_REFRESH_ENABLED=true`.

Trigger rules:

- explicit analyst requests such as `дозагрузи 1С`, `пересобери отчет`,
  `проверь себестоимость`, `не хватает маппинга`;
- or AI/OpenAI tool planning determines that the current report has
  `missing_cost`, `missing_mapping`, `needs_review` or `partial_source` and the
  question is about 1С cost, mapping, reconciliation, ОПиУ, batches, services or
  stock.

Read boundary:

- 1С calls are only OData `GET`;
- base collections: номенклатура, организации, характеристики, штрихкоды, цены,
  запасы, запасы по складам;
- extended registers: продажи, доходы/расходы, партии, партии УСН, партии
  КУДиР;
- WB service/UPD checks: `Document_ПоступлениеТоваровУслуг` and
  `Document_ПоступлениеТоваровУслуг_Услуги`;
- unavailable optional collections are marked `partial_source`; the system must
  not substitute zero values.

Job behavior:

1. Create `data_refresh_jobs` with status `queued`.
2. Reject if another active job exists for the same tenant/source report.
3. Save read-only snapshots under `data/onec_auto_refresh/<job_id>/`.
4. Rebuild workbook through reusable backend Python service, not shell.
5. Import the workbook as a new `report_run`.
6. Never patch the source report.
7. If any required step fails, set job status `failed`, write a safe error type,
   and do not create a new `report_run`.

AI/UI events:

- `Нашел нехватку 1С-данных`;
- `Дозагружаю 1С read-only`;
- `Пересчитываю отчет`;
- `Создан новый отчет`.

Safe API/chat payload may include job id, status, source/new report id, row
counts and hashes. It must not include raw 1С payloads, OData URLs with
credentials, `.env` values, tokens, SQL errors or traceback.

Audit actions:

- `onec_auto_refresh_requested`;
- `onec_auto_refresh_started`;
- `onec_auto_refresh_source_loaded`;
- `onec_auto_refresh_failed`;
- `onec_auto_refresh_report_created`;
- `ai_onec_auto_refresh_completed`.

## Scheduled WB/1C Source Refresh

`source refresh` is the scheduled successor to the legacy 1C-only refresh. It is
disabled by default and starts only when
`SHUMEYKO_SOURCE_REFRESH_ENABLED=true`.

Modes:

- `daily`: reads a rolling WB window plus current 1C/mapping lineage, but does
  not publish a new report run because a rolling WB window is not a full report
  period;
- `weekly` and `full`: read the configured full period and may publish a new
  `report_run`;
- `onec-only`: compatibility mode for 1C-only rebuilds over the latest WB
  snapshot.

Credential source:

- production scheduler uses encrypted tenant integrations from
  `tenant_integrations`;
- `.env` is allowed only for explicit local CLI/backfill runs with
  `--credential-source env`;
- `hash_only`, disabled, missing or undecryptable tenant integrations set
  `needs_configuration` and must not call external APIs.

Lineage tables:

- `source_refresh_runs` stores tenant, mode, period, credential source,
  `snapshot_set_id`, status and linked report ids;
- `source_refresh_collections` stores mandatory/optional source status, row
  counts, snapshot hashes and raw snapshot directory/file pointers;
- `source_snapshot_rows` is the generic idempotent raw-row lineage table for
  weekly report list, 1C OData, mapping metadata and small WB Finance
  snapshots. A WB Finance collection larger than
  `SHUMEYKO_SOURCE_REFRESH_WB_PERSIST_ROW_LIMIT` is not duplicated row-by-row
  in PostgreSQL: immutable JSON remains the authoritative raw snapshot, while
  `source_refresh_collections` keeps its row count, snapshot hash, raw path and
  `rowPersistence.status=skipped_large_snapshot`.
- WB Finance and WB Content pagination use separate configured request delays;
  the conservative Finance delay must not be applied to product-card pages.
  A full final page at configured `max_pages` is recorded as `partial_source`
  for product cards and weekly report list instead of being labelled loaded.

Mandatory sources are WB Finance detail, 1C nomenclature, organizations,
barcodes, sales register and mapping. Their failure blocks a new report.
Optional sources such as weekly report list, storage, promotion, stock and
service/OPIU extensions may create a report only with `needs_review`.

Source refresh never publishes a report automatically. It creates a staff-only
draft; after financial acceptance, a separate explicit `publish_report` call
applies the publication gate and atomically switches `is_current`.

`/api/health` scopes latest/finished source-refresh status to the configured
`SHUMEYKO_SOURCE_REFRESH_TENANT`. A later diagnostic canary for another tenant
must not degrade the Shumeyko cabinet health or replace its latest refresh id.

The publication gate derives tax rules exclusively from the target draft and
its organization profiles. It never inherits ОСНО requirements from the current
published report. ОСНО-specific P&L and input-VAT checks apply only to target
rows whose confirmed organization profile is ОСНО; a confirmed new УСН draft
therefore does not receive false blockers from an older ОСНО report.

Historical acceptance snapshot as of 2026-07-10 used two immutable staff
drafts: primary finance period `2026-03-01..2026-07-10` and stock-control
period `2026-04-10..2026-07-10`. That snapshot does not identify the live
report; operations always resolve the target draft from the database by
explicit `report_id`. The shorter draft was used only to validate complete
92-day provider-window stock coverage and was never a publication candidate.

Mapping freshness is a separate source health check against the project-owned
mapping service. If current mapping view is missing or has blocking
`missing`/`ambiguous` rows for mandatory marketplace items, the run is blocked
or published only with `needs_review` according to readiness rules. A stale
fallback file under `data/onec_marketplace_mapping/` is diagnostic context, not
the primary freshness signal.

Every created report run receives `SourceLoad` rows copied from refresh
collections. The client-facing cabinet uses readiness/freshness over
`SourceLoad`, not raw snapshots, so raw WB/1C payloads remain staff-only and
local.

Raw-row persistence errors are source quality errors. Mandatory source failure
blocks publication. Нулевые хранение и приемка считаются подтвержденными только
при загруженном контрольном WB-источнике с полным покрытием периода и явным
нулевым результатом; иначе прибыль не считается подтвержденной и report run
остается staff draft.

Каждая пересборка сначала создает immutable staff draft и копирует в
`SourceLoad` фактические нижележащие коллекции: `source_refresh_run_id`,
обязательность, статус, число строк и snapshot hash. `publish_report` не меняет
`is_current` и возвращает конфликт при любом финансовом блокере. Успешная
публикация выполняется одной транзакцией: прежний current получает
`superseded`, но остается доступен сотрудникам для аудита.

## Staff-Only Client Draft Workflow

В виджетах AI/клиентского вывода для ролей `consultant` и `admin` есть
отдельный режим `Клиентский черновик`. Роль `client` не видит вкладку, API,
версии, замечания аналитика, историю доработок и внутренний evidence этого
процесса.

Workflow:

1. Аналитик пишет внутреннее замечание или выбирает быстрое действие:
   `Собрать черновик`, `Сократить`, `Сделать мягче`, `Добавить что проверить`,
   `Уточнить ограничения`, `Проверить по фактам`.
2. `AiAnalyst.refine_client_draft` получает только расчетную витрину, latest
   draft, замечание аналитика и safe evidence. Raw snapshots, секреты, SQL,
   внешние payload и write-capable источники не используются.
3. Каждая AI-доработка или ручное сохранение создает новую ревизию
   `ai_client_drafts`.
4. Аналитик может вручную отредактировать текст и нажать `Сохранить версию`.
5. Финальные действия: `Скопировать клиенту`, `Скачать Markdown`,
   `Пометить готовым`. Отправки email, Telegram, Bitrix24 или CRM в этом scope
   нет.

Клиентский текст всегда состоит из разделов:

- `Ключевой вывод`;
- `Факты`;
- `Что требует проверки`;
- `Ограничения`;
- `Следующий шаг`.

В клиентском тексте запрещены raw tool names и debug/status labels, включая
`draft_management_report`, `tool_completed`, `tool_started`, traceback/debug
фрагменты, "я как AI/ИИ", внутренние комментарии и неподтвержденные причины
возвратов.

Если OpenAI недоступен, stylistic refinement не имитируется. Для существующего
черновика API возвращает сообщение `AI недоступен, черновик не изменен` и не
создает новую ревизию. Для первого черновика допустим deterministic base из
`management_report_text` и расчетной витрины.

Audit actions:

- `ai_client_draft_created`;
- `ai_client_draft_refined`;
- `ai_client_draft_saved`;
- `ai_client_draft_finalized`.

## AI UX And Streaming

AI-аналитик в кабинете показывает не raw reasoning модели, а безопасную
операционную трассу:

- какие read-only tools были вызваны;
- какие KPI, SKU, статусы или месяцы стали evidence;
- какие ограничения источников применены;
- когда ответ собран локальным fallback из-за отсутствия или ошибки OpenAI.

`POST /api/ai/threads/{id}/messages/stream` использует Server-Sent Events:

- `status`: вопрос принят, анализ запущен;
- `tool_started`: разрешенный инструмент начал работу;
- `tool_completed`: инструмент завершен, payload содержит только safe summary,
  evidence и ограничения;
- `answer_source`: ответ собран через OpenAI или локальный deterministic
  fallback по расчетной витрине;
- `assistant_done`: ответ сохранен;
- `final`: финальный текст ответа;
- `error`: безопасная ошибка без SQL, traceback или секретов.

Клиентская роль видит только safe trace. `consultant` и `admin` могут видеть
дополнительные служебные labels tool names/status, но не raw prompts, SQL,
секреты, payload внешних API или скрытые рассуждения модели.

## Tenant Integrations

Ключи клиента живут в контуре tenant, а не в профиле пользователя или
консультанта. Начиная с v2.10 интеграции являются реестром read-only
подключений клиента, потому что у одного клиента может быть несколько
WB-кабинетов, несколько 1C баз и разные роли ключей. Начиная с v2.11
интеграция должна быть связана с клиентским бизнес-слоем: WB API подключение
может создавать или обновлять `wb_cabinets`, а 1С подключение может создавать
или обновлять `client_companies` только через safe metadata.

Базовые типы провайдера:

- `wb_api`: read-only доступ Wildberries;
- `onec_readonly`: read-only строка подключения или secret reference для 1С.

Контракт подключения:

- `provider`: стабильный ID подключения; основные слоты остаются `wb_api` и
  `onec_readonly`, дополнительные подключения используют формат
  `<providerBase>:<connectionKey>`;
- `providerBase`: базовый тип провайдера (`wb_api` или `onec_readonly`);
- `connectionKey`: `primary` для основного слота или безопасный технический ID
  дополнительного подключения;
- `connectionRole`: роль ключа, например `finance_reports`,
  `analytics_stocks`, `content_cards`, `cost_documents`,
  `stocks_warehouses`, `full_readonly`;
- `cabinetName`: человекочитаемое имя WB-кабинета или 1C базы;
- `organizationName`: организация/ИП, к которой относится доступ;
- `clientCompanyId`: optional stable id юрлица/организации 1С внутри клиента;
- `wbCabinetId`: optional stable id WB-кабинета внутри клиента;
- `isPrimary`: основной слот, который использует текущий штатный source refresh.

API:

- `GET /api/integrations`;
- `POST /api/integrations`;
- `PUT /api/integrations/{provider}`;
- `POST /api/integrations/{provider}/check`;
- `POST /api/integrations/{provider}/disable`.

Интеграции доступны только `consultant/admin`. API возвращает status, masked
`secretHint`, label, `providerBase`, `connectionRole`, `cabinetName`,
`organizationName`, `isPrimary`, `storageMode`, safe `lastCheck` и timestamps,
но никогда не возвращает полный secret. Audit events хранят только
provider/status, safe message, check mode, endpoint category и HTTP status без
тела ответа и без секрета.

Staff UI может создавать новую карточку подключения выбором `providerBase`
(`wb_api`, `onec_readonly`, `ozon_api`) и безопасного имени. Для WB это также
сохраняет карточку `wb_cabinets`; для 1С/Ozon UI открывает draft-карточку
настройки, которая не попадает в `tenant_integrations` до сохранения read-only
секрета через существующий `POST /api/integrations`.

Совместимость: текущий штатный source refresh читает основные слоты `wb_api` и
`onec_readonly`. Расширенный source refresh должен читать все enabled WB
подключения с ролью `finance_reports` или `full_readonly` для выбранного
клиента, сохранять lineage по каждому `wb_cabinet_id` и не публиковать общий
отчет клиента, если mandatory WB/1C источники по включенным кабинетам не прошли
правила готовности. Дополнительные подключения, не участвующие в расчете, можно
сохранять и проверять read-only, но они не должны попадать в отчет без явного
active flag.

Secret storage:

- если `SHUMEYKO_INTEGRATION_SECRET_KEY` настроен, новый secret сохраняется как
  encrypted ciphertext в `tenant_integrations.config_payload`;
- если ключ шифрования отсутствует или некорректен, secret сохраняется только
  hash-only, API показывает `storageMode=hash_only`, а live-check возвращает
  `check_failed` с инструкцией повторно сохранить ключ после настройки runtime;
- legacy hash-only записи нельзя использовать для внешних запросов, потому что
  полный secret не восстановим.

Read-only checks:

- `wb_api` делает lightweight `GET https://finance-api.wildberries.ru/ping`
  с `Authorization` header, чтобы проверить достижимость WB API, валидность
  токена и соответствие Finance category без чтения отчетов;
- `onec_readonly` принимает JSON, key-value строку с `baseUrl`, `username`,
  `password`, optional `verifySsl`, либо env-style ключи
  `ONEC_ODATA_BASE_URL`, `ONEC_ODATA_USERNAME`, `ONEC_ODATA_PASSWORD`,
  `ONEC_ODATA_VERIFY_SSL` и делает `GET <baseUrl>/$metadata` через Basic Auth;
- оба check не читают raw business data, не пишут во внешние системы, не
  возвращают response body и не подставляют нули при ошибках.

OpenAI key остается сервисным runtime secret; клиентский BYOK не входит в этот
шаг пилота.

# Security And Rollout

- Use HTTPS on `shumeiko.offonika.ru`.
- Set session cookies as `HttpOnly`, `Secure`, `SameSite=Lax`.
- Keep `X-Robots-Tag: noindex, nofollow, noarchive`.
- Serve `/api/*` through nginx to the FastAPI service.
- Remove public `/data/*.json` and `/downloads/*.xlsx` artifacts from the
  subdomain root.
- Export Excel only through the authenticated API.
- Generate analytical report artifacts only inside the allowed reports/export
  root and serve them only through authenticated report-scoped API endpoints.
- If server-side PDF conversion is unavailable, return a clear PDF status
  instead of publishing an empty or stale PDF.
- Keep generated reports and DB files out of Git.
- Bootstrap users manually by server-side script or admin command, never from
  public registration.
- Store OpenAI and external API keys only in runtime environment such as
  `/etc/shumeiko-web.env`; never put keys in Git, Markdown, HTML or JSON
  artifacts.
- Set `SHUMEYKO_INTEGRATION_SECRET_KEY` before using tenant live checks; rotate
  it only with a separate migration/re-save procedure for encrypted tenant
  secrets.
- Keep `SHUMEYKO_LIVE_CHECKS_ENABLED=false` until separate 1C/WB read-only
  smoke passes.
- Keep `SHUMEYKO_AUTO_REFRESH_ENABLED=false` until separate 1C read-only smoke
  confirms OData access, row limits and collection availability.
- Store generated user passwords only in root-only operational files or deliver
  them out of band; never commit or document actual passwords.

# Operations

Regular update path:

1. Rebuild the deterministic Excel MVP from snapshots.
2. Import the workbook as a new `report_run` through server-side command or
   `POST /api/admin/reports/import`.
3. Check `/api/reports/{id}/freshness`, KPI totals and Excel export.
4. Check `readiness.status`, `blockingReasons`, `reviewReasons` and
   `nextAction` before sending the report to the client.
5. Open `/cabinet`, log in as consultant/admin and confirm that the readiness
   panel, data-quality panel and review rows match the API payload.
6. Confirm audit events for import/export/AI tool calls.

Backups:

- PostgreSQL backups are created by `scripts/backup_web_db.py` through systemd
  timer or manual run.
- Keep retention short by default and keep backup archives outside Git.

Monitoring:

- `scripts/check_web_cabinet_health.py` checks systemd, local `/api/health`,
  DB user/report counts and latest report date without printing secrets.

# Acceptance Criteria

- Unauthenticated user sees login, not report data.
- Authenticated user sees only tenant reports they are allowed to access.
- Consultant/admin with multiple clients sees a client switcher and can switch
  only between clients available through their access scope.
- Selecting a client reloads reports, integrations, readiness, AI context and
  filters for that client without leaking another client's values.
- Client role never sees another client through UI, API enumeration or direct
  guessed IDs.
- A single client can have multiple WB cabinets and multiple client
  companies/1C organizations; the dashboard defaults to all active cabinets and
  can filter to a specific cabinet/organization.
- WB cabinet and organization filters change KPI/detail slices but do not
  change tenant security boundary.
- KPI summary, filters, tables, SKU lookup and Excel export work through API.
- Admin can create, reset and disable users without public registration.
- Consultant/admin can review audit events.
- AI chat returns answers based on report tools and logs tool calls.
- AI widget shows messages, quick questions, safe step timeline, source status
  `OpenAI`/`fallback` and evidence cards for used tools.
- Consultant/admin can save, check and disable tenant integrations without full
  secrets being returned by API or audit.
- Tenant integrations with encrypted storage run real read-only WB Finance ping
  or 1C OData metadata checks; hash-only integrations fail visibly and require
  re-saving after secret-storage setup.
- Consultant/admin can open a staff-only client draft mode, refine/save
  revisions, finalize a version and export/copy Markdown without exposing the
  draft workflow to clients.
- Client role cannot read or infer staff client drafts through UI or API.
- Summary/freshness include `readiness`; consultant/admin sees client-draft
  readiness checks, client role does not infer staff draft state.
- KPI block uses tax-context-aware wording. With an unconfirmed profile it
  labels the canonical result `Маржинальный доход до налогов`, reports that the
  profile is missing and returns nullable tax KPIs instead of zeroes.
- Loss navigation separates product-margin losses, returns, penalty incidents
  without sales and rows with unconfirmed COGS.
- A report with a financial blocker shows `Финансовая проверка не пройдена`,
  cannot generate client recommendations and cannot replace the current report.
- `/`, `/cabinet`, `/ai` and `/integrations` serve a lightweight UI shell that
  does not embed report data before authenticated API calls.
- UI displays `ready`, `needs_review`, `partial_period`, `partial_source`,
  `source_coverage_gap` and `failed` states with stable mobile layout and safe
  text rendering.
- Products table has usable filters and horizontal scroll on mobile/tablet; no
  right-side columns are clipped by the page viewport.
- Streaming endpoint works, while the old non-stream message endpoint remains
  compatible.
- Live checks are read-only, audited and disabled unless configured.
- 1С auto-refresh is staff-only, feature-flagged, audited, creates a new
  `report_run`, leaves the source report unchanged, and marks partial 1С
  collections as `partial_source` without zero substitution.
- Manual/source-refresh API accepts an explicit `period_start`/`period_end` so
  staff can build the April acceptance snapshot before the full historical
  regression; the persisted run period is the source coverage boundary.
- Public URLs for JSON/Excel return 404 or do not exist.
- Existing Excel MVP tests and no-secrets checks still pass.

# Test Plan

- API tests for login, logout, `GET /api/me`, tenant isolation, report summary,
  filters, SKU lookup, protected Excel export, user management and audit rows.
- Multi-client API tests for `GET /api/clients`, client-scoped report lists,
  direct guessed-id denial, consultant access to assigned clients only and
  client-role isolation.
- AI tests with mocked/fallback model path and whitelisted tool outputs: no
  external API call required.
- Client-draft API tests for staff-only access, client denial, tenant boundary,
  revision creation, manual save, finalize, audit events and OpenAI-unavailable
  behavior without changing an existing draft.
- Report-readiness tests for `needs_review`, `ready`, `partial_period`,
  `partial_source`, `source_coverage_gap`, `failed`, tenant isolation and
  client-role redaction of staff-only draft reasons.
- Publication-gate tests prove that financial blockers return a conflict and do
  not change `is_current`; reconciliation tests prove that missing 1C sources
  remain null and independent WB/1C amounts do not create artificial zero
  deltas.
- UI shell tests for public login shell, protected API data loading, static
  assets, readiness API usage, products filters, horizontal table scroll, safe
  text rendering and responsive CSS.
- AI contract tests that client drafts contain required limitations and do not
  contain raw tool names/debug labels.
- AI streaming tests for `status`, `tool_completed`, `answer_source`, `final`,
  event persistence, answer source visibility and client-safe payload redaction.
- Integrations tests for staff-only access, add multiple connections,
  save/check/disable, tenant boundary, masked secret payloads and secret-free
  audit entries.
- Integration mapping tests that WB connections can be linked to
  `wb_cabinet_id`, 1C connections can be linked to `client_company_id`, and
  source refresh lineage preserves those ids.
- Frontend Playwright tests: consultant/admin sees `Клиентский черновик`, client
  does not; AI refinement updates the draft; manual save creates a version;
  `Скопировать клиенту` and `Скачать Markdown` are available; desktop/tablet and
  390px mobile do not overflow.
- Frontend Playwright tests for client switcher, default all-cabinets view,
  cabinet/organization filters and no stale data after switching clients.
- Live-check tests for disabled source, cached source, timeout/unavailable
  source and `needs_review` status without zero substitution.
- Auto-refresh backend tests for staff access, client 403, disabled flag without
  job, tenant boundary, active-job conflict, successful new `report_run`, failed
  job without new report, partial collection as `partial_source`, audit events
  and no raw payload/secrets in API/chat.
- AI contract tests that `refresh_onec_and_rebuild_report` is called for missing
  1С data, is not called for generic questions such as `что главное`, and cannot
  be triggered by client role.
- Import tests from an Excel-derived dashboard payload.
- Frontend smoke: login/authenticated API load, filters, AI widget and mobile
  overflow.
- Deployment smoke: HTTPS 200, `/api/health`, secure headers, no public data
  artifacts.

# Changelog

- 2026-07-10: v2.17 specified strict stock-history coverage, nullable tax
  context, signed VAT reconciliation, chronological return months and visible
  non-calculated development states for the three analytics blocks.
- 2026-07-10: v2.16 added the OSNO financial publication gate, immutable staff
  drafts with lower-level source lineage, independent nullable monthly
  reconciliation, canonical profit-before-NDFL UI and a separate penalty-only
  incident class.
- 2026-07-10: v2.15 changed cabinet monthly P&L and date filters from week-start
  attribution to weekly closing-date attribution and removed artificial
  month-end closing labels.
- 2026-07-10: v2.14 added source-backed financial document reconciliation for
  revenue with VAT and penalties, explicit `1С − WB` deltas and visible period
  boundary diagnostics in the cabinet.
- 2026-07-08: v2.13 switched mapping UX/readiness from 1С export upload to the
  project-owned marketplace/1C mapping service; file upload remains a bulk
  accepted import for unambiguous rows and manual-queue input for the rest.
- 2026-07-02: v2.12 clarified the mapping upload UX with visible 1С export
  instructions and an explicit preliminary-period client notice in next action
  copy.
- 2026-06-30: v2.11 added multi-client consulting-firm hierarchy: client
  switcher, `clients`, `client_companies`, `wb_cabinets`, stable row ids and
  explicit rule that WB cabinets are filters inside a client tenant, not
  separate tenants.
- 2026-06-24: product framing renamed to `AI-аналитик отчетов`; `Shumeyko v2`
  remains the pilot WB/1C implementation name.
- 2026-06-23: v2.10 upgraded tenant integrations from two fixed slots to a
  multi-connection read-only registry with provider base, connection role,
  cabinet/base name, organization name and primary-slot compatibility for the
  current source refresh.
- 2026-06-22: v2.9 added scheduled WB/1C source-refresh contract with tenant
  encrypted credentials, mode-specific publish rules, source lineage tables,
  mapping freshness and mandatory/optional source statuses.
- 2026-06-21: v2.8 added encrypted tenant secret storage, explicit hash-only
  refusal for live-check, WB Finance ping check and 1С OData metadata check.
- 2026-06-21: v2.7 added visible AI Analyst panel, answer source events and
  tenant-level integrations UI/API for WB and 1С read-only credentials.
- 2026-06-21: v2.6 added lightweight readiness UI shell over existing FastAPI
  APIs, static local assets, report-quality panel and staff-only client-draft
  visibility without adding a frontend build step.
- 2026-06-20: v2.5 added computed report readiness score in summary/freshness,
  readiness reasons, next action and client-role redaction for staff-only draft
  checks.
- 2026-06-20: v2.4 added staff-only AI-driven 1С auto-refresh,
  `data_refresh_jobs`, refresh API, read-only OData collection scope, new
  report_run behavior and AI/UI progress events.
- 2026-06-20: v2.3 added staff-only client draft workflow, revisioned
  `ai_client_drafts`, refine/save/finalize API and no-OpenAI no-change rule.
- 2026-06-20: v2.2 added safe AI event timeline, SSE message endpoint,
  evidence cards and explicit fallback visibility.
- 2026-06-20: v2.1 scope added user management, freshness/import, OpenAI
  tool boundary, live-check cache, backups, monitor and audit-view.
- 2026-06-20: accepted implementation target for Shumeyko v2.
