---
spec_id: "workspace-shumeyko-partners-wb-unit-economics-ai-web-cabinet-implementation"
title: "AI-аналитик отчетов: Shumeyko v2 web-кабинет"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
truth_scope: web-cabinet
truth_priority: 100
related_code: [src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/ai.py, src/wb_unit_economics/web/models.py, src/wb_unit_economics/web/repository.py, src/wb_unit_economics/web/refresh.py, src/wb_unit_economics/web/static/index.html, src/wb_unit_economics/web/static/app.js, src/wb_unit_economics/web/static/styles.css, sql/web_cabinet_schema.sql, scripts/import_web_report_from_excel.py, scripts/manage_web_users.py]
related_tests: [tests/test_web_app.py]
contracts: [wb_api_snapshot, onec_unf_cost_snapshot, sku_mapping, unit_economics_report, ai_analysis_summary]
depends_on: [docs/specs/wb-unit-economics-excel-mvp-implementation.md, docs/specs/wb-unit-economics-db-first-report-marts.md]
related_specs: [docs/specs/marketplace-1c-mapping-service.md, docs/specs/web-cabinet-runtime-contours.md]
changelog_path: docs/changelogs/web-cabinet.md
supersedes: [docs/specs/wb-unit-economics-client-web-cabinet.md]
rollout_required: true
updated_at: "2026-07-18"
---

# Implementation Status

Статус остается `accepted`. FastAPI/web UI и основной contract test suite
существуют, changelog фиксирует production-изменения, но это не заменяет полную
проверку всех acceptance criteria, browser scenarios и live deployment smoke.
До отдельной доказательной матрицы spec не переводится в `implemented`.
Information architecture `Аналитика и таблицы` принята как следующий UI-
контракт, но текущий runtime еще использует отдельный staff-only fragment
`#logistics`; принятие spec не означает, что новый маршрут уже развернут.

# Goal

Реализовать production-рамку пилота продукта `AI-аналитик отчетов` на
`analitika.offonika.ru`: авторизация, tenant boundary, хранение расчетных витрин в
PostgreSQL, управляемый Excel export и AI-аналитик отчетов поверх уже
рассчитанных данных.

`shumeiko.offonika.ru` является staff-only test-контуром. Точные runtime,
данные, promotion и rollback boundaries закреплены в
`docs/specs/web-cabinet-runtime-contours.md`.

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
- встроенная вкладка `Инструкция` (`#guide`) для авторизованного пользователя:
  она собирает разделы и действия из тех же названий и help-описаний, которые
  использует текущий UI, фильтрует staff-only действия по роли и не содержит
  отдельной вручную синхронизируемой копии навигации; contract test требует
  guide metadata для каждого верхнеуровневого раздела и действия кабинета, а
  также для статуса, этапов и всех основных действий `Данные и расчёт`;
- формирование фирменного клиентского аналитического отчета из сохранённого
  DB-first `report_id` в Markdown, DOCX и PDF, если на сервере доступен
  PDF-конвертер; Excel не является входом этого документа;
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

Начиная с v2.41 каждый новый `ai_thread` обязательно и неизменно связан с
`tenant_id`, `client_id`, `report_run_id`, создавшим его `user_id`, safe
`scope` текущего отбора и детерминированным `scope_hash`. Диалог доступен только
его владельцу; роль `admin` сама по себе не дает доступа к тексту чужого
диалога. Thread без конкретного report run не создается (`409`), а legacy thread
без report run архивируется миграцией. Любой optional `thread_id` в клиентском
черновике или refresh обязан совпадать с `report_id`, иначе операция возвращает
`409`.

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

Начиная с v2.12 `client_company` является канонической карточкой организации
1С внутри клиента. Разные полные, краткие и кабинетные написания хранятся как
алиасы и не создают отдельное юрлицо. Для одной основной базы 1С активная пара
`(client_id, onec_organization_id)` уникальна. Если алиас совпадает с несколькими
карточками, автоматический выбор запрещен и требуется стабильный ID. В каждой
строке нового отчета `client_company_id` обязан совпадать с
`wb_cabinets.client_company_id`; `company_cabinet_mismatch` является
непереопределяемым публикационным blocker и не может быть обойден публикацией
«с задачами». Техническое объединение карточек может менять только стабильные
ссылки и алиасы: расчетные суммы и исходные текстовые поля immutable report run
остаются без изменений.

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
Когда пользователю разрешён логистический сценарий, элементы этого уже
авторизованного списка аддитивно содержат безопасный `logisticsDataStatus` без
денежных значений и raw details. UI может предложить сотруднику более новый
`ready` report run только из этого списка. При выключенном client feature flag
поле не раскрывает клиентской роли наличие или статус скрытых draft.

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

Финансовые причины являются блокирующими для публикации, замены текущего отчёта
и клиентских рекомендаций: смешение методов P&L,
расхождение `profit` и `profitBeforeTax` до НДФЛ, неподтвержденный входящий НДС,
незакрытая себестоимость, неуспешный обязательный source lineage, отсутствие
подтверждения нулевых хранения/приемки, незакрытая независимая месячная или
документная сверка. При наличии такой причины UI показывает точный заголовок
`Финансовая проверка не пройдена`, а клиентский AI не формирует рекомендации и
возвращает HTTP 409. Эти причины не останавливают расчёт витрины, KPI и P&L и не
скрывают уже рассчитанные показатели в кабинете. Если расчётные факты доступны,
UI показывает их с пометкой `Предварительный расчёт: есть замечания к качеству
данных`; отсутствующие значения остаются явными `null`/`не рассчитано` и не
подменяются нулями.

UI readiness behavior:

- unauthenticated visitor sees only the login shell and no report data;
- начиная с v2.36 боковая навигация содержит вкладку `Инструкция`. Страница
  показывает рекомендуемый старт, назначение разделов и доступные действия,
  но не загружает отдельные report data. Карточки инструкции формируются в
  браузере из `data-guide-*` metadata живых контролов: видимое название берется
  из самого элемента, пояснение хранится рядом с ним, а staff-only карточки
  выводятся только для `consultant/admin`. Новый верхнеуровневый раздел или
  пункт меню действий без guide metadata считается contract regression;
- начиная с v2.38 `Инструкция` содержит отдельный нумерованный сценарий для
  вкладки `Проверки`: прочитать сводку запуска, проверить этапы и карточки
  источников, выполнить readiness-only проверку, при необходимости обновить
  клиентское сопоставление, использовать incremental refresh как обычный
  сценарий, запускать Ozon-only только для служебной витрины Ozon + 1С, а full
  refresh — только для первичной или восстановительной пересборки истории.
  `Обновить статус` только перечитывает состояние последнего запуска. После
  завершения пользователь переходит к `Что проверить в отчете`, проблемным
  строкам и сверке WB ↔ 1С. Названия кнопок в инструкции берутся из живых
  controls, а contract regression блокирует новое действие блока
  `source-refresh-actions` без `data-guide-*` пояснения;
- the authenticated cabinet uses one analyst workspace shell with a persistent
  navigation rail and four page entries: `Обзор`, `Проверки`,
  `Аналитика и таблицы` and `Инструкция`; a separate top-level `Логистика`
  entry is forbidden. `Отчёт клиенту` remains a report action, while
  `Настройки` is shown only to `consultant/admin` and opens the existing
  integrations widget rather than a new page;
- `Аналитика и таблицы` contains one nested scenario navigation with the stable
  order `Сводка`, `Товары`, `Логистика`, `Возвраты`, `Расходы WB`,
  `Исходные данные`. A role or feature flag may hide an unavailable scenario,
  but must not create another sidebar entry or change the order of the
  remaining scenarios;
- the browser URL may expose UI-only fragments `#overview`, `#checks`,
  `#checks/cost`, `#tables`, `#tables/summary`, `#tables/products`,
  `#tables/logistics`, `#tables/returns`, `#tables/wb-expenses`,
  `#tables/source` and `#guide`; `#tables` is an alias of
  `#tables/summary`. These fragments do not add server routes or API contracts,
  invalid fragments fall back to `#overview`, and browser Back/Forward restores
  the visible workspace without reloading report facts. A deep-link to a
  scenario unavailable to the current role or disabled by its feature flag
  falls back to the first permitted `Аналитика и таблицы` scenario and does not
  start its API request;
- the overview WB-expense card exposes the action `Разобрать логистику` only
  when the logistics scenario is permitted; it opens `#tables/logistics` and
  preserves the selected client, server-authorized `report_id`, cabinet,
  company, scheme and period filters. A query-string `report_id` is selected
  only from the reports already returned for the current role and tenant;
- the logistics first screen follows the answer-first and state contracts of
  `docs/specs/wb-logistics-cost-analysis-implementation.md`: total logistics is
  an accounting cost and profit effect, not an automatically avoidable loss or
  savings reserve; overlapping action rows cannot be presented as additive;
- `ready`, `partial`, `needs_rebuild`/`blocked`, an empty permitted slice and a
  request failure have distinct logistics surfaces. Unavailable values remain
  null, and stale figures are either cleared or explicitly marked unavailable
  for the current filter context;
- at 390 px the complete selected global context remains available: cabinet,
  company, period and scheme cannot be hidden with responsive CSS. Nested
  scenario controls are scrollable or reflow safely without page-level
  horizontal overflow, and focus moves to the scenario heading after a route
  change;
- after login, UI shows a client switcher when the user has more than one
  available client;
- `consultant/admin` can create a new client workspace from the topbar; after
  creation the UI switches to that client and prompts staff to add integrations
  before report data exists;
- selecting a client reloads only that client's reports, integrations, readiness
  and AI context;
- if a user has exactly one client, UI may load the latest available report for
  that client automatically;
- the compact context bar is the only visible global control for client,
  marketplace cabinet, period start and period end; the detailed row workspace
  keeps only table-local search/status/business filters while its hidden cabinet
  and date controls remain synchronized for backward-compatible requests;
- topbar does not expose an `Отчет` selector; selecting a client loads the
  current available report slice automatically;
- report meta, source freshness and client hierarchy are not repeated as a
  separate middle-screen block; the topbar and readiness strip are the canonical
  context, and mapping service entry appears only in the main next-action area;
- the top-left topbar message uses semantic color states for neutral information,
  success, review/warning and blocking/error information; the action area keeps
  report, management and session actions in separate responsive groups so
  `Выход` does not drift when action labels or available staff actions change;
- navigation entry `Отчёт клиенту` opens the staff/client output state as a
  modal widget over the current report instead of scrolling to a lower report
  section;
- staff navigation entry `Настройки` opens read-only WB/Ozon/1C tenant
  connections as a
  modal widget over the current report instead of scrolling to a lower report
  section or navigating away; the compatible `/integrations` deep link opens
  the same widget after the current client context loads;
- for `consultant/admin`, the `Проверки` workspace shows a separate
  `Данные и расчёт` panel before the quality task board.
  It loads independently from the integrations widget and exposes current
  source-refresh status, stages, collection statuses, fallback mapping upload,
  readiness check and the primary `Обновить и пересчитать` action. The
  `Интеграции` widget contains connection settings only;
- all user-facing operational labels and safe messages are shown in Russian:
  source-refresh modes such as `daily`/`full`, and terms such as `refresh`,
  `mapping`, `read-only`, `readiness`, `fallback`, `lineage` and `snapshot` are
  translated without changing their internal API values or stored contracts;
- workspace action `AI-аналитик` is visually emphasized with a library icon and opens
  the AI analyst as a modal widget over the current report instead of scrolling
  to a lower report section or navigating away; the compatible `/ai` deep link
  opens the same widget after the current client report loads;
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
- missing 1C cost opens the local `#checks/cost` workflow instead of turning the
  whole report into a wizard. Its stepper is `Найти строки` ->
  `Проверить себестоимость` -> `Подтвердить`; it derives counts from
  `quality.missingCostRows`, opens the existing `missingCost` drilldown and uses
  the existing report-scoped browser acknowledgement. The confirmation must
  explicitly state that it does not mutate 1C, source snapshots, calculations,
  readiness or publication status. The stepper is not shown for Ozon mode or
  unrelated checks;
- обычный `publish_report` остается строгим и отклоняет report с блокерами;
  отдельный staff-only `POST /api/reports/{report_id}/publish-with-tasks`
  требует явного подтверждения и причины, атомарно переключает current и пишет
  audit-событие `report_published_with_tasks`. Все `blockingReasons` остаются
  карточками `Исправить сейчас`, отсутствующие финансовые показатели остаются
  `null`, а клиентские финансовые рекомендации остаются заблокированными до
  фактического закрытия readiness;
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
  documents, OK rows, rows needing review, comparable quantity delta,
  commissioner-revenue delta, reference buyout amounts and missing 1С fact,
  and supports filters for search, status, period start/end,
  cabinet, organization, document type and `Только расхождения`; the
  same tab first shows financial reconciliation from
  `/api/reports/{id}/financial-document-reconciliation`: KPI pairs `WB`, `1С`
  and `Дельта 1С − WB` for comparable commissioner revenue with VAT and
  penalties, plus separate reference totals for WB buyout retail and 1С
  expense invoices net after deductions. The panel also shows `Выручка 1С за
  календарный период`: it contains both posted `ОтчетКомиссионера` and
  `РасходнаяНакладная` documents, and must equal the 1С gross-profit report
  under the same date and organization filters. It is followed by rows
  with the WB report, actual 1С documents, amounts, status and explanation;
  `Статья` filters the rows by revenue with VAT or penalties. The WB side uses
  report rows whose weekly closing date (`week + 6 days`) falls inside the
  selected period. For sales revenue, both WB and 1С use that same persisted
  sales-week closing date and the selected cabinet/organization; the actual
  1С posting date remains visible but does not move a cross-month sales week.
  Penalties continue to use the actual incoming-invoice date. Buyout retail
  and expense-invoice net amounts have `amountsComparable=false`, an empty
  delta and status `Справочно`; their correctness is controlled by the
  comparable positive quantity in the technical block. For comparable values
  the signed delta is always `1С − WB`, tolerance for `Сходится` is 1 ruble,
  and unavailable source facts remain missing instead of being coerced to
  source zero;
  the dashboard KPI `Единый стандарт WB ↔ 1С` is a separate accounting
  reconciliation only: it uses 1C posting dates, WB commissioner retail and
  1C net buyout invoices after quantity confirmation. Its zero delta does not
  alter WB retail, WB sales-week revenue, product P&L or any 1C primary date;
  a missing or quantity-mismatched buyout makes this KPI unavailable instead
  of forcing it to zero;
  clicking the KPI `Выкупы: 1С нетто − WB розница` opens a read-only
  drilldown scoped to the active period and WB cabinet. It shows the WB report
  week, date and number of the 1С invoice, WB retail amount, 1С net invoice
  amount, their informational delta, quantity-check status and a plain-language
  reason. Missing 1С invoices and quantity mismatches are listed first with the
  concrete action to load/find the document; matched rows explain that the
  monetary delta is expected because the bases differ. The additive endpoint
  `/api/reports/{id}/buyout-reconciliation` does not change source data or the
  existing reconciliation URLs.
- the AI widget remains a modal overlay and may render a compact visual context
  strip from already loaded `summary.kpis`, `summary.quality` and readiness;
  this presentation does not change the AI request, SSE or response contracts
  and must show an explicit empty state when report facts are unavailable.
  the existing generic document-load reconciliation remains below the
  financial block for quantity, payout and completeness controls; the
  `Юнит-экономика` tab keeps filters for search, status, period start/end,
  month, cabinet, organization, scheme and loss class before loading rows
  through `/api/reports/{id}/rows`, and shows revenue, profit, margin and unit
  profit for every report row. The visible table starts with product name,
  WB/1C articles, barcode and `nmId`, keeps the period and quantity block next,
  then shows the individual components of profit: cost, commission, logistics,
  storage, acceptance, promotion, penalties and acquiring without a repeated
  cumulative `Остаток после ...` column after every component. A separate
  explicit P&L VAT adjustment reconciles displayed gross WB service amounts
  with the accepted profit, and report/document lineage is placed at the end.
  The final row metric is labelled as the result after included taxes, not as
  full net business profit. The table uses server-side pagination: the counter must say
  which range is currently visible (`1–100 из 1553`), and previous/next controls
  must make every filtered row reachable. A preset such as `Убыточные продажи`
  remains visibly active and its total is never presented as the unfiltered
  assortment total. Quick presets are session-only: a fresh page load starts
  from `Все` and must not restore a previously selected loss preset from browser
  storage;
- unit-economics filters auto-apply on change/input; the UI does not require a
  separate `Применить` action, while `Сбросить` clears the slice explicitly;
- `Показатели` is recalculated from the filtered `rows` response, so
  cabinet/date/detail filters change the displayed money KPIs together with the
  table; the strip also shows management-estimated `Упущенные продажи` from
  `report_lost_sales_rows` as lost revenue for the current report run/cabinet,
  and lays out the cards as two rows with revenue, profit, margin, lost sales,
  sales, net sales, returns, return rate, revenue per sale and loss-row count;
- `Показатели` также разделяет расходную базу и бухгалтерский контроль:
  `Расходы WB в товарном P&L` находятся в блоке юнит-экономики, а
  `Услуги WB по документам 1С` и `Сверка расходов WB ↔ 1С` — в `Контроль 1С`.
  Все три карточки открывают один read-only drilldown. Аддитивный endpoint
  `/api/reports/{id}/marketplace-expense-reconciliation` наследует фильтры дат,
  кабинета и организации, возвращает контрольные группы и строки документов,
  сохраняет отсутствующий источник как `null` и не блокирует рассчитанный P&L
  WB. Для старого immutable report без нормализованных строк услуг выводится
  `Нужна пересборка отчёта`;
- summary exposes `lostSalesCoverage`, `taxContext`, `taxProfileSync` and
  calendar month metadata. `taxProfileSync` отдельно показывает живой профиль
  организации в PostgreSQL и профиль, фактически примененный к immutable
  report run; staff получает `liveStatus`, `reportStatus`, `needsRebuild`,
  безопасный source refresh id и пояснение, клиент — только безопасное состояние
  расчета без hashes и draft lineage.
  A missing tax profile, absent stock history or incomplete provider window is
  rendered as a visible `Не рассчитано` state with the exact coverage/source
  reason. A complete provider window shorter than the report period is rendered
  as `Рассчитано за доступный период`; it is never extrapolated or rendered as
  a confirmed zero and the analytics block is not removed;
- `taxContext.calculated` remains `false` when settings of any report
  organization were not loaded from 1C or were not applied for part of the
  report period, when `vatDeductionMode=unknown`, or when the loaded tax object
  is not supported by the current methodology;
  `readiness.blockingReasons[]` exposes `tax_profile_unconfirmed` in these
  cases;
- если живой профиль готов, но hash `onec_tax_profiles` не совпадает с
  `SourceLoad` отчета или в строках отчета остался `missing_tax_profile`, UI
  показывает `Подтвержден в 1С, но не применен в текущем отчете`, сохраняет
  warning tone и запускает staff-only auto draft; он не называет профиль
  неподтвержденным и не делает старые налоговые суммы подтвержденными;
- when WB limits daily stock history to its last three calendar months,
  `lostSalesCoverage` keeps the full requested report period and the actual
  provider window separately; the uncovered earlier days remain explicit.
  If every selected WB cabinet completely covers the same contiguous provider
  window, lost sales are calculated only inside that window. Sales, revenue and
  contribution inputs from boundary weeks are prorated by overlapping calendar
  days; unavailable earlier days are never extrapolated or converted to zero;
- the existing report date and cabinet filters also scope lost sales. The API
  intersects the selected dates with the common complete provider window of the
  selected WB cabinets and recalculates the estimate from persisted daily stock
  plus Decimal weekly finance intervals. For `2026-05-01..2026-05-31` inside the
  accepted `2026-04-10..2026-07-10` provider window, coverage is therefore
  `31/31`; a selection outside that window remains explicitly not calculated;
- each new `report_lost_sales_rows` record keeps an internal versioned
  `calculation_context` with daily WB stock and source weekly intervals. Public
  `lostSales[]` keeps its existing shape, while `lostSalesCoverage` adds
  `requestedPeriodStart` and `requestedPeriodEnd`. Older immutable reports
  without this context are not reinterpreted as filter-capable and require a
  rebuild;
- `lostSales[].lostContributionMargin` is the canonical preliminary estimate
  before tax. `lostProfit` remains a compatibility alias. Aggregate lost-sales
  KPI is nullable unless every selected cabinet has complete daily stock
  coverage for either the report period or the explicitly displayed common
  provider window. `lostSalesCoverage` exposes `fullCoverage`,
  `calculationPeriodStart`, `calculationPeriodEnd` and `extrapolated=false`;
- начиная с v2.35 первый экран `Обзора` использует фиксированную иерархию:
  один блок основных KPI, затем `Аналитика` с динамикой продаж первым графиком,
  затем readiness command board. `Дополнительные показатели`, `Статус исходных
  данных`, подробный `Контроль 1С` и полная сверка входящего НДС находятся во
  вкладке `Проверки`; два набора карточек раскрываются по запросу и по умолчанию
  не увеличивают высоту экрана;
- `Контроль перед отправкой` находится во вкладке `Проверки` рядом с контролем
  источников и расширенными показателями, так что line-quality blockers и
  problem-row action не конкурируют с финансовой интерпретацией на `Обзоре`.
  v1 renders embedded dependency-free
  visualizations from
  `summary.monthly`, `summary.expenses`, `summary.lostSales`,
  `summary.liquidityRows` and `summary.kpis`: grouped column charts for money
  dynamics, a P&L-style unit economics table, horizontal bars for top losses
  and return columns with return-rate context;
- начиная с v2.37 первый уровень `Обзора` показывает восемь основных KPI:
  в первом ряду — выручку WB без НДС, себестоимость 1С, расходы WB,
  маржинальный доход и маржу; во втором — `Итого к перечислению`, продажи и
  возвратность. `Итого к перечислению` является суммой сохранённых
  `forPaySum` финансовых отчётов WB в текущем срезе и показывается справочно:
  это не подтверждение фактического банковского платежа и не источник выплаты
  1С. Если `forPaySum` отсутствует во всех строках, KPI остаётся `null`, а не
  подменяется расчётом `выручка − расходы`. Выручка с НДС, чистые продажи,
  возвраты, выручка на
  продажу, убыточные строки, штрафы и налоговый мост остаются доступны в
  раскрываемом блоке `Дополнительные показатели` во вкладке `Проверки`; если
  налоговый профиль не
  применён, шесть пустых налоговых карточек заменяются одной явной карточкой
  статуса без подмены значений нулями. Карточка выручки WB показывает вторичной
  строкой календарную выручку 1С с НДС или явный статус её отсутствия; это не
  превращает разные базы в одну сумму и не дублируется отдельной карточкой;
- начиная с v2.39 основной блок `Показатели` содержит десять KPI в фиксированной
  сетке 5×2: выручка WB без НДС, себестоимость 1С, расходы WB, управленческая
  прибыль и маржинальность; затем прибыль до налогов, маржинальность до налогов,
  `Итого к перечислению`, продажи WB и возвратность. Карточка прибыли после
  применения профильных налогов переносится из `Дополнительных показателей` и
  не дублируется там.
  `kpis.marginAfterTax` равен `profitAfterTax / revenue_for_pnl` только при
  применённом налоговом профиле, сходящемся налоговом мосте и ненулевой базе
  выручки; иначе значение остаётся `null`. Для ОСНО обе карточки явно сообщают
  `По юнит-экономике · НДФЛ ИП не включён`; НДС к уплате остаётся отдельным
  обязательством и повторно не уменьшает товарный P&L. Если профиль не применён
  или мост не сходится, обе карточки показывают `Не рассчитано`, а не оценку;
- начиная с v2.40 основные KPI-карточки используют компактную типографику без
  сокращения финансовых названий и без изменения значений: заголовок имеет
  размер `14px`, зону высотой `36px` и занимает не более двух строк; значение
  имеет размер `clamp(22px, 1.55vw, 26px)`, а на мобильном экране — `19px`.
  Высота карточки составляет `142px`, внутренние отступы сохраняются. Денежные,
  процентные и количественные значения, а также состояние `Не рассчитано`, не
  разрываются между строками (`white-space: nowrap`, `overflow-wrap: normal`,
  `word-break: keep-all`) и используют табличные цифры. Адаптивная сетка
  содержит пять колонок при ширине от `1180px`, три колонки в диапазоне
  `761–1179px` и две колонки до `760px`; страница и карточки не создают
  горизонтальную прокрутку. Подсказка открывается по наведению и клавиатурному
  фокусу, ограничена шириной `320px` и выравнивается внутрь viewport для первой
  и последней карточек каждого ряда. Публичные API и формулы KPI не меняются;
- `/api/reports/{id}/rows` возвращает в корневом `kpis` тот же полный набор
  агрегатов, что и в `analytics.kpis`. В частности, `Расходы WB` и
  `Итого к перечислению` не должны исчезать после автоматического применения
  фильтров. Расходы WB берутся из рассчитанного товарного P&L на применённой
  налоговой базе; наличие или отсутствие документов услуг 1С влияет только на
  отдельную бухгалтерскую сверку и не обнуляет этот KPI;
- `Динамика продаж` занимает всю ширину аналитического блока и повторяет
  принятый в управленческой витрине визуальный принцип: продажи показаны
  нейтральными столбцами, выручка и маржинальный доход — отдельными линиями,
  маржа — линией по правой процентной шкале. Прогноз не выводится без
  подтверждённого источника. Каждый месяц доступен мышью и клавиатурой,
  показывает точные значения во всплывающей подсказке и открывает существующую
  месячную детализацию. График честно показывает месяцы текущего загруженного
  отчёта и подписывает их диапазон; если в отчёте есть 12 месяцев, диапазон
  обозначается как год. Месяцы вне `summary.monthly` не достраиваются и не
  прогнозируются; API, формулы и состав `summary.monthly` не меняются;
- `Аналитика` also works as a review navigator: a compact
  `Что разобрать первым` row prioritizes missing 1C cost, mapping, WB ↔ 1C
  reconciliation, loss rows, lost sales and returns. For `consultant/admin`,
  the `Сопоставление WB ↔ 1C` card opens the separate staff-only mapping-service
  widget already filtered to WB and the analyst queue; it is not embedded in
  `Интеграции`. Other card/chart clicks open the relevant drilldown, detail tab
  or unit-economics preset without mutating source data;
- the unit-economics tab exposes quick row presets `Все`, `Убыточные`,
  `Без себестоимости`, `Mapping`, `Возвраты` and `К проверке`; `preset=returns`
  filters rows with returns or positive return rate;
- analytics charts are read-only. Initial summary shows the current report run
  as a whole, while the compact global cabinet and period controls refresh the
  filtered analytics payload; table-local search, status and business presets
  do not silently redefine report-wide financial totals;
- return months are ordered by machine-readable `monthStart`; an incomplete
  month stays last, shows `daysElapsed/daysInMonth`, and is not presented as a
  like-for-like comparison with complete months;
- VAT reconciliation is a full-width control in `Проверки`, not a chart on
  `Обзоре`. It preserves signed amounts and shows charges, reversals and net
  separately, includes cabinet/organization and source evidence status, and
  follows the global cabinet, period and organization slice through
  `analytics.taxInputReconciliation`; it has no independent cabinet filter;
- VAT reconciliation is shown only where input VAT may be deducted. For
  `vatDeductionMode = allowed` it shows the semantic table; for `mixed` it
  excludes organization rows whose resolved mode is `not_allowed` or
  `not_applicable`; for `unknown` it shows only a warning that the tax profile
  must be confirmed; for `not_allowed` and `not_applicable`, including USN with
  special VAT rates, the block is hidden. Ozon article economics remains a
  separate overview block and does not reuse the WB VAT reconciliation node;
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
- в шапке staff-интерфейса действие называется `Сформировать отчет` и открывает
  отдельный мастер, а не сразу скачивает Excel. Мастер явно показывает клиента,
  контур `WB + 1С` или служебную диагностику `Ozon + 1С`, период по настройкам
  клиента либо собственные даты и текущий статус запуска. Действия `Создать
  Excel за …` и `Проверить источники без создания` являются отдельными
  кнопками; readiness-only проверка передает `dry_run=true`, не создает Excel и
  не использует чекбокс режима;
- текущий опубликованный Excel показывается в мастере отдельной нейтральной
  карточкой с точным периодом и прямой ссылкой по `report_id`. Он определяется
  из списка отчетов только по одновременным признакам `isCurrent=true` и
  `publicationStatus=published`, явно помечен как не относящийся к настройкам
  нового отчета и никогда не считается результатом текущего запуска;
- состояние мастер-сессии содержит идентификатор source-refresh запуска,
  выбранные режим и период, статус и `newReportRunId`. Глобальный
  `latestSourceRefresh`, включая фоновый daily refresh, не переводит новую
  сессию на следующий шаг и не показывается как результат пользовательского
  запуска. Настройки блокируются только на время запуска, а действие
  `Сформировать другой период` очищает сессию;
- результат мастера существует только при наличии `newReportRunId` и все его
  скачивания используют этот точный `report_id`: `report_created` показывает
  зеленую карточку `Excel за … готов`, а `needs_review` с новым отчетом —
  желтую карточку `Excel создан с замечаниями и пока не опубликован как
  текущий`. Ошибка или `needs_review` без нового отчета не показывают старый
  Excel как результат. DOCX/PDF можно подготовить или обновить в той же
  карточке; при их ошибке UI сообщает `Не удалось подготовить DOCX и PDF.
  Сформированный Excel остаётся доступен` без HTTP-кода;
- шаги мастера являются семантическим списком с `aria-current`, после
  завершения фокус переносится на карточку результата. На мобильном обе кнопки
  полноширинные, основное действие идет первым;
- мастер передает выбранные `period_start`/`period_end` в staff-only source
  refresh API, не обещает фильтрацию по одному кабинету, если backend собирает
  все активные подключения клиента, и явно сообщает, что `ozon-only` не
  публикует клиентский отчет;
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
  `snapshot_set_id`, `base_source_refresh_run_id`, status and linked report ids;
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
mapping service. Loaded `missing`/`ambiguous` rows are review-only: they do not
block WB revenue, sales, returns or lost-sales calculation over the available
stock-history provider window. They keep 1C cost and profit nullable only for
the affected products and remain visible as `mapping_review`. A completely
missing or failed mapping source remains a source failure. A stale fallback
file under `data/onec_marketplace_mapping/` is diagnostic context, not the
primary freshness signal.

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

Штатный SSE UI восстанавливает последний активный thread текущего пользователя
для выбранного отчёта через `GET /api/ai/threads?report_id=<id>&limit=1`.
После перезагрузки страницы сохранённые сообщения, safe events и источник
последнего ответа снова видимы; UI не очищает серверную историю. Во время
запроса поле и кнопка блокируются, статус явно показывает `Анализирую…`, а
обрыв stream без `final` отображается как безопасная ошибка.

Модальный AI widget имеет отдельные grid-строки для header, report context,
quick questions и прокручиваемой chat workspace. Длинный текст переносится
внутри message/timeline, форма не выходит за viewport. На узком или низком
экране сам widget получает вертикальную прокрутку вместо обрезки через
`overflow:hidden`; поле вопроса и кнопка остаются доступны после прокрутки.

Клиентская роль видит только safe trace. `consultant` и `admin` могут видеть
дополнительные служебные labels tool names/status, но не raw prompts, SQL,
секреты, payload внешних API или скрытые рассуждения модели.

### AI core v2.41

- Runtime developer prompts хранятся отдельными Git-versioned Markdown-файлами
  `src/wb_unit_economics/web/prompts/ai_analyst.md` и `client_draft.md`,
  упаковываются вместе с Python package и не редактируются через кабинет.
  Отсутствующий, пустой или содержащий незаполненный обязательный placeholder
  prompt считается ошибкой реализации, а не поводом молча ослабить ограничения.
- Для чистого короткого приветствия, благодарности, прощания или вопроса о
  возможностях первый Responses request использует `tool_choice=none`: ответ не
  содержит фактов отчёта и не создаёт tool events/citations. Любой смешанный или
  фактический вопрос по отчёту сохраняет `tool_choice=required`, поэтому модель
  не может ответить финансовыми показателями без server-side evidence.
- OpenAI вызывается до deterministic fallback; fallback не запускает tools
  заранее и переиспользует уже полученный результат tool call после ошибки
  модели. Один function call, включая `refresh_onec_and_rebuild_report`, может
  быть исполнен не более одного раза в рамках одного ответа.
- В повторный Responses request передаются SDK output-items без `model_dump()`:
  response-only поля (`status`, `namespace`) не попадают в новый input.
- Запросы используют `store=false`,
  `include=["reasoning.encrypted_content"]`, hashed `safety_identifier` и
  runtime timeout. Шифрованное reasoning-состояние не сохраняется в БД или UI.
- Контекст содержит не более 20 последних user/assistant сообщений и не более
  32 000 символов. Текущий вопрос не дублируется.
- KPI, readiness, quality и месячная динамика берутся из канонического
  `report_summary_payload`; SQL-поиск строк используется только для ограниченной
  evidence-выборки. Отсутствующая прибыль до налогов остается `null` и
  выводится как `не рассчитано`, а не как ноль.
- Assistant message сохраняет safe `citations`: `reportId`, `clientId`,
  `scopeHash`, имя server tool и только отображаемые идентификаторы evidence
  строк. Raw payload, prompt, SQL и reasoning в citations не допускаются.
- Ограничение неполного месяца строится из `meta.periodStatus`; статическая
  формулировка про июнь запрещена для другого периода.
- `/api/health` публикует только безопасные AI runtime metadata: факт настройки,
  имя модели и состояние feature flag ChatKit, но не ключи или prompts.

### ChatKit boundary v2.41

ChatKit является опциональной заменой только UI/transport слоя. По умолчанию
`SHUMEYKO_CHATKIT_ENABLED=false`, штатный SSE остается активным. При включении
разрешена только custom self-hosted server integration с существующей
same-origin session, CSRF/tenant/report/owner проверками и теми же серверными
tools. Web component использует актуальный custom-server contract:
`apiURL=/api/chatkit` и same-origin custom `fetch`; domain key не требуется и
не публикуется через health/config. Agent Builder workflow и Agents SDK не
являются источником финансовой логики. Attachments и внешние actions отключены.
До отдельного acceptance теста feature flag не включается в production;
`/api/ai/config` сообщает UI выбранный transport и ограничения, не раскрывая
конфигурацию OpenAI.

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

- Use HTTPS on `analitika.offonika.ru` и `shumeiko.offonika.ru`.
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
  `/etc/shumeiko-web-prod.env`; never put keys in Git, Markdown, HTML or JSON
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
- `summary` and `freshness` log safe execution timing without report rows,
  source payloads or integration credentials. Requests slower than five seconds
  are warnings; the PostgreSQL statement timeout remains 15 seconds and is not
  used as a substitute for query optimization.

Large-report loading:

- `GET /api/reports/{id}/summary` computes row statistics with bounded SQL
  aggregates and must not materialize every `report_unit_row` ORM object.
- `GET /api/reports/{id}/freshness` reuses the same compact statistics for row
  count and readiness and must not reload the full report mart for tax-profile
  status.
- the cabinet renders a successful summary before loading freshness and other
  staff-only panels. A freshness failure leaves KPI visible with a warning; a
  summary failure clears stale KPI and offers an explicit retry for the same
  guarded client-load context.

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
- For the production reference report with at least 65,000 rows, summary and
  freshness return HTTP 200 without statement timeout; the first request after
  service restart completes within eight seconds and an immediate repeat
  within three seconds.
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
- KPI block uses tax-context-aware wording. When tax settings from 1C were not
  loaded or applied, it labels the canonical result `Маржинальный доход до
  налогов`, reports the missing settings and returns nullable tax KPIs instead
  of zeroes; it does not request separate manual confirmation.
- Loss navigation separates product-margin losses, returns, penalty incidents
  without sales and rows with unconfirmed COGS.
- A report with a financial blocker shows `Финансовая проверка не пройдена`,
  keeps available KPI and P&L values visible with a preliminary data-quality
  notice, cannot generate client recommendations and cannot replace the current
  report.
- `/`, `/cabinet`, `/ai` and `/integrations` serve a lightweight UI shell that
  does not embed report data before authenticated API calls.
- `#guide` открывает встроенную инструкцию; ее названия разделов и действий
  совпадают с текущими UI controls, а клиентская роль не видит staff-only
  карточки `Настройки` и `Добавить клиента`.
- Боковая навигация содержит `Аналитика и таблицы`, не содержит отдельный пункт
  `Логистика`, а вложенная навигация сохраняет порядок `Сводка / Товары /
  Логистика / Возвраты / Расходы WB / Исходные данные` среди доступных роли
  сценариев.
- `#tables/logistics`, browser Back/Forward и действие `Разобрать логистику`
  открывают один и тот же разрешенный срез без потери фильтров. Недоступный роли
  или выключенный feature flag сценарий не загружает logistics API и безопасно
  возвращает пользователя к первому разрешенному сценарию.
- Логистический сценарий автоматически использует самый новый `ready` report
  run из серверно отфильтрованного списка отчётов текущего клиента, если
  выбранный отчет старее. Техническая ревизия не меняет `report_id` в URL,
  текущую публикацию и контекст остальных разделов; client role и произвольный
  идентификатор не могут использовать этот механизм для доступа к draft.
- При неполных границах периода точная логистика показывается за весь выбранный
  календарный срез, а доля в выручке и влияние на прибыль — за явно подписанный
  максимальный вложенный интервал полных недель из `financialComparison`.
  Финансовые KPI полного периода остаются `null`, без пропорционального
  восстановления и без смешивания периодов в одной карточке.
- Логистический first screen не называет всю сумму логистики устранимой потерей
  или резервом экономии, различает пересекающиеся зоны проверки и имеет разные
  состояния для `ready`, `partial`, `needs_rebuild`/`blocked`, пустого среза и
  ошибки запроса без zero/stale fallback.
- На ширине 390 px все значения глобального среза остаются доступными, вложенная
  навигация не создает page-level overflow, а после перехода фокус установлен на
  заголовке выбранного сценария.
- Для `consultant/admin` инструкция по `Проверкам` различает обычное обновление
  последних данных, Ozon-only витрину и редкую полную пересборку, объясняет
  значения сводки/этапов/карточек источников и заканчивается разбором
  проблемных строк; клиентская роль не видит staff-only source-refresh actions.
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
- Every long-running production, scheduler or direct CLI refresh keeps an
  independent database heartbeat while external WB/1C requests are in progress.
  Source-file/manifest activity is also exposed as a safe aggregate timestamp,
  so the UI does not report a dead background process while 1C pages are still
  being written. A stale warning is blocking only when neither heartbeat nor
  recent snapshot activity confirms liveness.
- The cabinet distinguishes a rolling `daily` data refresh from report
  generation: while `daily` is active it says `Данные обновляются`, never
  `Отчёт формируется`; only report-producing modes show report-build wording.
  User-facing status text does not expose the internal term `worker`.
- A mandatory source with status `needs_review` remains a publication blocker,
  but is described as successfully loaded data requiring verification. It is
  not grouped under `Источник не загрузился`; genuine transport, access,
  schema, configuration and partial-load failures retain the error wording.
- Consultant/admin can open `Сформировать отчет`, choose the report contour and
  period, run a readiness-only check or start generation and follow the exact
  wizard-session status. The current published Excel remains a separate neutral
  download, while a green or warning result card and its direct download appear
  only for that session's non-empty `newReportRunId`; background refreshes never
  advance the wizard.
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
- Large-report tests keep the public summary free of `unitRows`, preserve KPI,
  tax and VAT-reconciliation parity, and cap `report_unit_rows` selects at
  eight for summary and three for freshness. UI tests cover summary failure,
  freshness-only failure, retry and switching clients while a request is in
  flight.
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
- Frontend guide contract: hash routing и sidebar state для `#guide`, генерация
  карточек безопасными DOM methods, role filtering и обязательное
  `data-guide-*` покрытие верхней навигации, фильтров, action menu и всех кнопок
  `source-refresh-actions`; отдельный negative test отклоняет новую кнопку
  `Данные и расчёт` без пользовательского пояснения.
- Frontend information-architecture contract: единственный sidebar entry
  `Аналитика и таблицы`, фиксированный порядок вложенных сценариев, alias
  `#tables -> #tables/summary`, прямой `#tables/logistics`, Back/Forward,
  сохранение разрешенного draft и глобального среза, а также отсутствие
  logistics API-вызова для client role при выключенном client flag.
- Frontend logistics-state contract: semantic guard против трактовки всей
  логистики как устранимой потери, явная неаддитивность пересекающихся зон,
  отдельные `ready`/`partial`/`needs_rebuild`/`blocked`/empty/error состояния,
  отсутствие stale/zero fallback и видимость полного глобального среза на
  ширине 390 px.
- Deployment smoke: HTTPS 200, `/api/health`, secure headers, no public data
  artifacts.

# Changelog

Полная история изменений вынесена в `docs/changelogs/web-cabinet.md`.
