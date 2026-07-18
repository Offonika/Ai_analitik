---
spec_id: "workspace-shumeyko-ai-report-analyst-multi-report-cabinet"
title: "AI-аналитик отчетов: многотипный кабинет"
doc_type: spec
domain: "report-automation"
status: accepted
owner: "engineering"
audience: ["engineering", "consultant", "operations"]
source_of_truth: true
truth_scope: "multi-report-cabinet"
truth_priority: 100
related_code:
  - src/wb_unit_economics/web/models.py
  - src/wb_unit_economics/web/repository.py
  - src/wb_unit_economics/web/report_kinds.py
  - src/wb_unit_economics/web/reports/
  - src/wb_unit_economics/web/app.py
  - src/wb_unit_economics/web/static/index.html
  - src/wb_unit_economics/web/static/app.js
  - src/wb_unit_economics/web/static/sortable-tables.js
  - src/wb_unit_economics/web/static/sortable-tables.css
related_tests:
  - tests/test_web_database.py
  - tests/test_db_first_publication.py
  - tests/test_web_app.py
  - tests/test_multi_report_cabinet.py
contracts:
  - unit_economics_report
  - month_close_control_report
  - tax_load_report
ai_sections:
  status: "Статус документа"
  goal: "Goal"
  scope: "Scope"
  registry: "Report Kind Registry"
  contract: "Shared Data Contract"
  code_structure: "Code Structure Rule"
  ui: "UI Contract"
  api: "Proposed API Compatibility"
  checks: "Advisory And Enforced Checks"
  acceptance: "Acceptance Criteria"
  tests: "Test Plan"
depends_on:
  - docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md
  - docs/specs/wb-unit-economics-db-first-report-marts.md
related_specs:
  - docs/specs/month-close-control-report-implementation.md
  - docs/specs/tax-load-report-implementation.md
  - docs/specs/accounting-reports-smart-process-onepage.md
supersedes: []
rollout_required: true
updated_at: "2026-07-18"
---

# Статус документа

Это accepted implementation spec узкой staff-only advisory v1. Она расширяет
действующий контракт web-кабинета и DB-first публикации, но не разрешает
клиентскую публикацию бухгалтерских видов, `accountant_confirmed` или enforced
business checks. Статус остается `accepted` до сквозной проверки реального
пути 1С -> evidence -> сохраненный payload -> Web/Excel.

Согласованные направления:

- в кабинете появляется пользовательский переключатель `Вид отчета`;
- внутреннее поле называется `report_kind`, потому что `report_type` уже
  используется в WB-контуре для типа финансового документа; существующий
  enum `OnecReportKind` в `src/wb_unit_economics/contracts.py` описывает тип
  документа 1С внутри расчета юнит-экономики и по смыслу не совпадает с
  `ReportRun.report_kind` — оба имени сохраняются, а различие фиксируется
  в docstring обоих полей при реализации;
- первый каталог содержит юнит-экономику маркетплейсов, контроль закрытия
  месяца и налоговую нагрузку;
- новый бухгалтерский и налоговый контур сначала доступен только
  `consultant/admin`;
- первый пользовательский результат для новых видов — web-сценарий и Excel;
- операционный контур закрытия к зарплате ведется одной карточкой
  смарт-процесса на клиента, организацию и месяц с двумя связанными задачами по
  `month_close_control` и `tax_load`;
- в первом rollout обязанности бухгалтера и консультанта может выполнять один
  ответственный специалист, но подтверждение фактов и утверждение клиентского
  текста остаются разными audit-событиями;
- проверки полноты в первой версии работают как предупреждения, чтобы методику
  можно было безопасно тестировать; обязательные security и tenant-ограничения
  не ослабляются.

# Goal

Превратить текущий кабинет одного отчета в общую оболочку `AI-аналитика
отчетов`, где консультант выбирает клиента, вид отчета и период, а затем работает
с отдельным воспроизводимым сценарием расчета, проверки и экспорта.

Новая оболочка не должна смешивать методики разных отчетов в одном универсальном
payload. Общими остаются идентификация клиента, права, `report_run`, публикация,
lineage, артефакты и audit. Расчетные строки, проверки и бизнес-статусы остаются
контрактами конкретного `report_kind`.

# Scope

Входит:

- каталог поддерживаемых видов отчетов;
- поле `report_kind` в `report_runs`;
- выбор вида отчета в общей панели контекста;
- текущий report run по связке `tenant + client + report_kind`: опубликованный
  для юнит-экономики и внутренний draft для бухгалтерских видов;
- отдельная история запусков и артефактов каждого вида;
- совместимость существующих отчетов юнит-экономики;
- capability metadata вида отчета: период, доступные роли, фильтры, web-разделы,
  Excel export и readiness mode;
- staff-only запуск и просмотр новых бухгалтерских сценариев;
- мягкий режим бизнес-проверок на пилотном этапе;
- audit просмотра, переключения, генерации и экспорта.

# Out Of Scope

Не входит:

- произвольный конструктор отчетов;
- создание пользовательских формул в web;
- автоматическая запись в WB, Ozon, 1С, банк, CRM, FinKoper или налоговые
  системы;
- автоматическая отправка отчета клиенту;
- общая клиентская публикация закрытия месяца или налоговой нагрузки до
  отдельного согласования;
- группировка видов по категориям в первой версии;
- замена бухгалтерского или налогового заключения решением AI.

# Users And Decisions

- `consultant` выбирает клиента и вид отчета, формирует внутренний draft,
  разбирает предупреждения и утверждает клиентский текст.
- `admin` управляет доступами и техническим состоянием источников, но не
  подтверждает налоговые факты вместо бухгалтера.
- `client_*` в первой версии продолжает видеть только разрешенные опубликованные
  отчеты юнит-экономики.
- бухгалтер подтверждает налоговые факты в специализированном сценарии; способ
  фиксации подтверждения должен оставлять audit record.

В первом rollout `consultant` и бухгалтер являются одним ответственным
специалистом на уровне операционного процесса. Это не отменяет раздельные
действия подтверждения фактов и утверждения текста и не меняет технические
права клиентских ролей.

# Operational Smart Process Boundary

Каноническая модель Канбана, двух связанных задач и закрытия к зарплате задана
в `docs/specs/accounting-reports-smart-process-onepage.md`.

Кабинет остается источником воспроизводимых `report_id`, расчетов и
артефактов. Смарт-процесс хранит только workflow-состояние, безопасные ссылки и
подтверждения и не пересчитывает показатели.

В первой версии допускается ручная отправка финального `tax_load` клиенту после
подтверждения ответственным специалистом. Это действие фиксируется в
смарт-процессе и не означает автоматическую отправку или клиентскую публикацию
из кабинета. Ответ клиента не блокирует закрытие к зарплате: при отсутствии
ответа создается отдельная задача контрольного контакта (`follow-up`).

Смарт-процесс реализуется как отдельный модуль web-кабинета по принятой
ONEPAGE-концепции и требует отдельного rollout. Прямая запись карточек, стадий
или задач во внешние CRM, включая FinKoper, отнесена ко второму этапу.

# Report Kind Registry

Первый каталог:

| `report_kind` | Название в UI | Период | Доступ в первой версии | Выход |
| --- | --- | --- | --- | --- |
| `marketplace_unit_economics` | Юнит-экономика | Произвольный диапазон | Действующие роли | Web + действующие экспорты |
| `month_close_control` | Контроль закрытия месяца | Календарный месяц | `consultant/admin` | Web + Excel |
| `tax_load` | Налоговая нагрузка | Месяц + с начала года | `consultant/admin` | Web + Excel |

Категория отчета в первой версии не хранится. Если каталог станет большим,
можно добавить отдельное отображаемое поле `report_family`, не меняя стабильные
значения `report_kind`.

Registry для каждого вида должен задавать как минимум:

- стабильное значение `report_kind` и русское название;
- разрешенные роли;
- гранулярность периода;
- применимые глобальные фильтры;
- поддерживаемые артефакты;
- контракт summary и detail marts;
- режим бизнес-проверок `advisory` или `enforced`;
- доступность клиентской публикации.

Registry первой версии реализуется константой в коде, а не таблицей БД: трех
видов недостаточно для динамической конфигурации, а изменение каталога и так
требует изменения контрактов и тестов. Включение видов в конкретной установке
управляется настройкой web-приложения `enabled_report_kinds`; по умолчанию
включена только юнит-экономика. Отдельная инфраструктура feature flags не
создается.

# Shared Data Contract

В `ReportRun` добавляется обязательное поле:

```text
report_kind: marketplace_unit_economics | month_close_control | tax_load
```

Существующие записи получают
`report_kind = marketplace_unit_economics`. Миграция не определяет вид по title,
имени Excel или `lineage_type`.

Вместе с `report_kind` в `report_runs` добавляется nullable поле
`organization_id`: для бухгалтерских видов оно обязательно, для
`marketplace_unit_economics` остается пустым. Организация 1С — часть
идентичности бухгалтерского отчета, а не только фильтр отображения: у одного
клиента может быть несколько организаций, и их отчеты не должны вытеснять
друг друга.

Общие поля `client_id`, `tenant_id`, `period_start`, `period_end`,
`source_coverage_start`, `source_coverage_end`, `methodology_version`,
`publication_status`, `is_current`, lineage и artifacts сохраняются.

Правило текущей публикации:

```text
не более одного is_current=true
для tenant_id + client_id + report_kind + organization_scope

organization_scope = organization_id для бухгалтерских видов
organization_scope = пусто для marketplace_unit_economics
```

Публикация `tax_load` не снимает текущий `marketplace_unit_economics` и
наоборот. Публикация бухгалтерского отчета одной организации не снимает
current той же связки по другой организации. Экспортный fallback, latest
lookup, AI context и история также ограничиваются тем же `report_kind` и той
же организацией.

Правило current обеспечивается снятием предыдущего `is_current` и установкой
нового в одной транзакции. Для бухгалтерских видов эта операция не меняет
`publication_status = draft` и не открывает отчет клиентским ролям.
Дополнительно правило закрепляется partial unique index по
`tenant_id + client_id + report_kind + organization_scope` там, где движок БД
его поддерживает (PostgreSQL); для SQLite действует транзакционная гарантия
приложения.

Расчетные данные не складываются в одну универсальную таблицу:

- `unit_economics_report` остается контрактом юнит-экономики;
- `month_close_control_report` хранит контрольные процедуры и доказательства;
- `tax_load_report` хранит налоговые показатели, календарь и подтверждения.

Для бухгалтерской генерации `SourceRefreshCollection` дополнительно хранит
`organization_id`. Нормализованный evidence уникален в границе
`refresh_run_id + report_kind + organization_id`; в payload фиксируются версия
контракта, период, организация, SHA-256 и snapshot IDs исходных коллекций.
Для локально фильтруемых бухгалтерских коллекций raw GET-страницы могут
покрывать историю до выбранного периода, но нормализуемый combined snapshot и
его `row_count` включают только строки заданного окна. Общий cap обновления не
должен обрывать чтение до достижения этого окна.
`month_close_control_reports` и `tax_load_reports` хранят по одному
валидированному payload на `report_id`. Web и Excel читают именно его и не
пересчитывают отчет при просмотре или экспорте.

`report-generation` имеет стадии `queued`, `refreshing_sources`,
`materializing_evidence`, `building_report`, затем `completed` или `failed`.
Такой запуск не участвует в health, latest source refresh и индикаторе свежести
источников. Если evidence-контракт не создан вообще, запуск завершается ошибкой
source integrity и не создает пустой current report.

# Code Structure Rule

Оболочка не должна растить существующие монолитные модули. Контракт, payload
builder, проверки и Excel builder каждого вида живут в отдельных модулях вида
(например, `web/reports/<report_kind>.py` и отдельный фронтенд-модуль
сценария), а общая оболочка подключает их через registry. В общие модули
(`repository.py`, `app.js`) добавляется только маршрутизация по `report_kind`
и общие для всех видов операции, но не методика конкретного вида.

# UI Contract

Глобальный контекст:

```text
Клиент -> Вид отчета -> Период -> фильтры выбранного сценария
```

Общая оболочка сохраняет разделы `Обзор`, `Проверки`, `Таблицы` и
`Инструкция`, но их содержимое и внутренние вкладки определяет `report_kind`.
Таким образом пользователь не изучает новую навигационную систему для каждого
отчета, но получает другой рабочий сценарий.

Правила переключения:

- смена вида не запускает загрузку источников или расчет автоматически;
- кабинет загружает current report выбранного вида для клиента;
- если current отсутствует, показывается безопасное пустое состояние и действие
  `Сформировать отчет` для staff;
- marketplace cabinet показывается только для применимых видов;
- организация 1С — обязательная часть контекста бухгалтерских видов: без
  выбранной организации их current не определен;
- выбранный вид можно сохранять локально отдельно для каждого клиента;
- URL должен восстанавливать выбранный вид без доступа к отчету другого tenant.

Все HTML-таблицы общей оболочки и report-specific сценариев поддерживают
сортировку по каждой смысловой колонке. Первый выбор сортирует по возрастанию,
повторный — по убыванию; направление видно в заголовке и доступно через
`aria-sort`. Числа, денежные суммы, проценты и даты сравниваются по значению,
строки — без учета регистра, пустые значения остаются внизу. Заголовки доступны
с клавиатуры, а активная сортировка сохраняется после безопасной перерисовки.

Таблица без постраничной загрузки сортирует полный локально загруженный набор.
Для таблиц с server pagination сортировка применяется в БД ко всему
отфильтрованному набору до `offset/limit`, использует только разрешенный mapping
колонок и стабильный вторичный ключ, а затем возвращает первую страницу.
Перестановка только текущих 100/250 DOM-строк для paginated-таблицы запрещена.
Колонки действий без собственного значения явно исключаются из сортировки.

# Proposed API Compatibility

Предлагаемые интерфейсы:

- `GET /api/clients/{client_id}/report-kinds` — доступные пользователю виды;
- `GET /api/clients/{client_id}/reports?report_kind=...` — история одного
  вида; для бухгалтерских видов дополнительно передается `organization_id`;
- `GET /api/reports/latest/summary?client_id=...&report_kind=...` — current
  summary одного вида; для бухгалтерских видов дополнительно передается
  `organization_id`;
- `POST /api/clients/{client_id}/reports/generate` — staff-only асинхронная
  генерация внутреннего draft по `reportKind`, `organizationId` и
  `periodMonth=YYYY-MM`; заголовок `Idempotency-Key` обязателен;
- `GET /api/report-generations/{generation_run_id}` — безопасный статус
  конкретного запуска и созданный `reportId`, когда расчет завершен;
- `GET /api/reports/{report_id}/scenario` — report-specific payload без raw
  snapshots, секретов, клиентских URL и локальных путей;
- `GET /api/reports/{report_id}/rows` принимает whitelist-параметры `sort_by`
  и `sort_direction=asc|desc`; сортировка выполняется до пагинации и не меняет
  агрегаты, фильтры или tenant/report scope;
- существующие report-scoped endpoints продолжают проверять `report_id`,
  tenant и client;
- до завершения миграции отсутствие `report_kind` в legacy-запросе означает
  `marketplace_unit_economics`, но новый UI всегда передает значение явно.

Черновой состав ответов:

```text
GET /api/clients/{client_id}/report-kinds
{
  "reportKinds": [
    {
      "kind": "month_close_control",
      "title": "Контроль закрытия месяца",
      "periodGranularity": "calendar_month",
      "requiresOrganization": true,
      "roles": ["consultant", "admin"],
      "artifacts": ["web", "excel"],
      "readinessMode": "advisory",
      "clientPublication": false
    }
  ]
}

GET /api/clients/{client_id}/reports?report_kind=...&organization_id=...
{
  "items": [
    {
      "id": "...",
      "reportKind": "month_close_control",
      "organizationId": "...",
      "periodStart": "2026-06-01",
      "periodEnd": "2026-06-30",
      "publicationStatus": "draft",
      "isCurrent": true,
      "generatedAt": "..."
    }
  ]
}
```

`POST /reports/generate` только создает queued run и возвращает HTTP 202 с
`generationRunId`, `status`, `stage`, nullable `reportId` и `deduplicated`.
Повтор одного `Idempotency-Key` возвращает тот же run. Отдельная таблица хранит
`Idempotency-Key -> generationRunId + requestFingerprint`; повтор ключа с
другим видом, организацией или месяцем возвращает 400. Параллельный запуск той
же связки client + report kind + organization + month прикрепляет новый ключ к
активному run; новый ключ после завершения создает ревизию.
`GET /api/report-generations/{id}` возвращает текущую `stage`, безопасное
сообщение и nullable `reportId`, не раскрывая raw error внешнего источника.
Summary и scenario payload остаются контрактами конкретного `report_kind`.
API не возвращает raw snapshots, секреты, клиентские URL и локальные пути
артефактов.

# Advisory And Enforced Checks

Проверки делятся на два класса.

Всегда жесткие:

- аутентификация и tenant isolation;
- read-only граница внешних интеграций;
- запрет публикации секретов и raw client data;
- валидность `report_kind` и report contract;
- соответствие `report_id` клиенту и tenant;
- сохранение lineage и версии методики.

Мягкие на первом этапе:

- неполное покрытие бухгалтерского чек-листа;
- отсутствие части подтверждений;
- неподтвержденный налоговый показатель;
- незавершенная сверка, если она не нарушает source integrity.

Мягкие проверки показывают предупреждение и разрешают staff открыть web-draft и
скачать Excel для тестирования. Они не превращают отсутствующие значения в нули
и не разрешают клиентскую публикацию новых видов. Переход отдельного правила в
`enforced` выполняется только через обновление accepted spec, тесты и rollout
note.

# Security, Audit And Retention

- Все новые источники по умолчанию read-only.
- Новые виды наследуют tenant boundaries существующего кабинета.
- `report_kind`, период, методика, source snapshot set и пользовательское
  подтверждение входят в audit context.
- Audit фиксирует выбор вида, просмотр, запрос и дедупликацию генерации,
  завершение или ошибку расчета и Excel export.
- Excel хранится как защищенный report artifact, а не в Git.
- Retention не удаляет source lineage current или аудируемого report run.
- AI получает только нормализованные факты выбранного `report_id` и не меняет
  статусы, источники или подтверждения.

# Errors And Edge Cases

- Вид доступен клиенту, но отчет еще не сформирован: показать empty state, не
  подменять другим видом.
- В URL указан недоступный `report_kind`: вернуть безопасный fallback без утечки
  существования отчета.
- У клиента current есть только для юнит-экономики: бухгалтерские виды остаются
  пустыми.
- Публикация одного вида не должна supersede другой.
- У клиента несколько организаций 1С: current и история бухгалтерского вида
  ведутся по каждой организации отдельно.
- Legacy report без `report_kind` после миграции считается юнит-экономикой.
- Excel export по draft бухгалтерского вида помечается как предварительный.
- Частичное покрытие источников отображается статусом, а не нулевыми суммами.
- Отсутствие отдельных бухгалтерских подтверждений остается advisory;
  отсутствие evidence-контракта является source-integrity ошибкой.
- Для `month_close_control` evidence без строк ни штатной ОСВ, ни проверенного
  RecordType fallback также является source-integrity ошибкой: generation
  завершается без нового report run и без смены current.

# Acceptance Criteria

- Каталог возвращает только разрешенные роли и виды.
- Переключение вида меняет scenario payload без смешения строк разных контрактов.
- Current определяется по `tenant + client + report_kind`, а для
  бухгалтерских видов — дополнительно по организации 1С.
- Существующие отчеты и ссылки юнит-экономики продолжают работать.
- Staff может открыть предварительный web-сценарий и Excel новых видов при
  бизнес-предупреждениях.
- Security, tenant, read-only и source-integrity ограничения остаются жесткими.
- AI и экспорт используют тот же `report_id` и `report_kind`, который видит
  пользователь.
- `month_close_control` и `tax_load` независимо адресуются по `report_id`, чтобы
  смарт-процесс мог связать одну карточку с двумя раздельными задачами и
  артефактами.
- Клиентские роли не получают новые виды до отдельного разрешения.
- Каждая отображаемая таблица сортируется по любой колонке мышью и клавиатурой;
  индикатор, `aria-sort`, типизированное сравнение и положение пустых значений
  соответствуют UI-контракту также после динамической перерисовки строк.
- В `Юнит-экономике`, рейтинге логистики и цепочках заказов сортировка охватывает
  весь отфильтрованный набор, а первая и следующая страницы продолжают единый
  стабильный порядок без повторов и пропусков.

# Test Plan

- schema migration: legacy rows получают `marketplace_unit_economics`;
- uniqueness/current tests по `client_id + report_kind + organization_scope`;
- публикация одного вида не меняет current другого;
- публикация бухгалтерского вида одной организации не меняет current другой
  организации;
- настройка `enabled_report_kinds` скрывает выключенный вид из каталога и API;
- выключенный вид возвращает 404 также в summary, scenario, export, latest и
  direct-report маршрутах;
- одинаковый idempotency key с другим fingerprint возвращает 400, а новый ключ
  активной связки возвращает тот же run;
- `report-generation` не меняет health/latest freshness;
- e2e: обезличенные raw ответы 1С -> source rows -> evidence -> сохраненный
  payload -> Web/Excel, без прямой подстановки `normalizedEvidence`;
- API permissions и tenant-boundary tests;
- UI switch, empty state, Back/Forward и сохранение выбора;
- shared table sorting assets подключены ко всем страницам с таблицами;
  проверяются оба направления, числа, даты, строки, пустые значения,
  клавиатурное управление, `aria-sort` и повторная сортировка после рендера;
- API/UI pagination tests проверяют server-side сортировку до `offset/limit`,
  возврат на первую страницу, whitelist sort keys и пустые значения внизу;
- report-specific payload contract tests;
- Excel artifact smoke для новых видов;
- advisory warnings не блокируют staff draft/export;
- enforced security failures нельзя перевести в warning;
- `.venv/bin/python scripts/validate_specs.py`;
- `.venv/bin/python scripts/validate_docs_manifest.py`;
- `.venv/bin/python scripts/validate_llm_docs.py`;
- `.venv/bin/python scripts/validate_no_secrets.py`.

# Rollout And Rollback

1. Добавить `report_kind` и `organization_id` с безопасным default и выполнить
   миграцию legacy rows.
2. Включить registry и API через настройку `enabled_report_kinds` только для
   staff.
3. Добавить переключатель без изменения текущего default юнит-экономики.
4. Подключить `month_close_control`, затем `tax_load` в advisory mode.
5. Сверить web и Excel каждого вида на одном локальном report run.
6. Отдельно согласовать клиентскую публикацию и усиление business gates.

Rollback убирает новые виды из `enabled_report_kinds` и скрывает selector,
сохраняя legacy `marketplace_unit_economics`. Новые report runs не удаляются
и не подменяют current юнит-экономики.

# Deferred Decisions

- Окончательный обязательный состав подтверждений закрытия месяца.
- Способ и источник фиксации подтверждения бухгалтера.
- Условия и дата перевода отдельных бизнес-проверок из `advisory` в `enforced`.
- Нужна ли категория `report_family` после первых трех видов.
- Когда клиентские роли получают доступ к бухгалтерским отчетам.

Вопросы, требующие ответа бухгалтера, собраны с владельцем и сроком в
`docs/decisions/2026-07-14-accounting-reports-accountant-questions.md`.
Они не блокируют accepted staff-only advisory v1.

# Changelog

- 2026-07-18: paginated-таблицы переведены с сортировки текущей DOM-страницы на
  стабильную server-side сортировку полного отфильтрованного набора до
  `offset/limit`; клиентский клик возвращает первую страницу.
- 2026-07-18: исправлен self-triggered цикл shared table sorter: обновление
  индикатора направления стало идемпотентным, версия JS asset повышена для
  сброса browser cache, а rollout требует headless-browser smoke динамической
  перерисовки и обоих направлений сортировки.
- 2026-07-18: все статические и динамические таблицы кабинета получили единый
  контракт локальной сортировки по колонкам с типизированным сравнением,
  клавиатурным управлением и доступным индикатором направления.

- 2026-07-16: уточнена целевая система смарт-процесса: отдельный модуль
  web-кабинета без внешних интеграций; интеграция с FinKoper перенесена на
  второй этап, упоминание Bitrix удалено.
- 2026-07-16: первоначальная модель внешнего смарт-процесса зафиксировала одну
  карточку на клиента, организацию и месяц, две связанные задачи, одного
  ответственного специалиста, ручную отправку `tax_load` и неблокирующий ответ
  клиента. В тот же день целевая система была уточнена следующей записью
  changelog: v1 реализуется внутри web-кабинета, без записи в Bitrix или другую
  CRM; клиентская публикация остается отдельным rollout-решением.
- 2026-07-14: результаты первых accounting canary исключены из приемки после
  обнаружения неверного tenant/client scope; canary CLI получил разрешение
  клиента по уникальному имени и проверку явной пары tenant/client.
- 2026-07-14: технические canary в ошибочно выбранном tenant подтвердили
  сквозной evidence/Web/Excel, но исключены из бухгалтерской приемки;
  `enabled_report_kinds` оставлен в rollback-состоянии, report runs и audit
  сохранены, статус остается `accepted`.
- 2026-07-14: production schema `2026_07_14_accounting_evidence_v2` и новый
  web/worker code развернуты после полного backup; оба бухгалтерских вида
  оставлены выключенными до контрольного real-data month-close run.
- 2026-07-14: после технического аудита статус временно возвращен в `accepted`:
  production source-refresh не материализовал бухгалтерские evidence-контракты;
  приняты обязательные исправления worker, идемпотентности, health и rollback.
- 2026-07-14: зафиксированы evidence v2, стадии асинхронного worker, отдельная
  таблица idempotency keys, запрет пустого current и исключение служебной
  генерации из freshness/health.
- 2026-07-14: реализованы registry, миграция, сохраненные scenario payload,
  staff-only API, web-переключатель, Excel, audit и rollback-настройка; полный
  набор тестов пройден.
- 2026-07-14: spec принята для узкой staff-only advisory v1; добавлены
  generation/scenario API, идемпотентность и обязательный audit.
- 2026-07-14: уточнения после ревью: разграничение с `OnecReportKind`,
  `organization_id` в `report_runs` и current с учетом организации, механизм
  включения видов через настройку `enabled_report_kinds` вместо feature flag,
  черновой состав API-ответов, registry-константа и правило модульной
  структуры кода.
- 2026-07-14: создан draft многотипного кабинета; зафиксированы три
  `report_kind`, current по клиенту и виду, staff-only запуск новых сценариев,
  web + Excel и мягкие бизнес-проверки первой версии.
