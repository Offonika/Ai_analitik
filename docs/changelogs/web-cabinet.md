---
title: "AI web cabinet changelog"
doc_type: changelog
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md"
updated_at: "2026-07-15"
---

# AI web cabinet changelog

Полная история изменений accepted web-cabinet implementation spec. Текущие
нормативные требования остаются в
`docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md`; этот файл
хранит только хронологию изменений.

- 2026-07-15: v2.46 закрепил клиентские KPI `Прибыль до НДФЛ` и
  `Маржинальность до НДФЛ`; технические поля `profitAfterTax` и
  `marginAfterTax` сохранены для обратной совместимости.
- 2026-07-15: v2.45 вынес developer prompts AI-аналитика и клиентского
  черновика в упакованные Markdown-файлы и запретил запуск отчётных tools для
  чистых приветствий, сохранив обязательный tool для фактических вопросов.
- 2026-07-15: v2.44 распространил viewport-safe вертикальную прокрутку AI
  widget на низкие экраны, чтобы поле вопроса не обрезалось при ограниченной
  высоте окна.
- 2026-07-15: v2.43 закрепил восстановление последнего SSE thread после
  перезагрузки, явные loading/error состояния, отсутствие повторной отправки
  исторических SSE events и viewport-safe прокрутку AI widget.
- 2026-07-15: v2.42 синхронизировал self-hosted ChatKit с актуальным OpenAI
  custom-server contract (`apiURL` и same-origin custom `fetch`), исключил
  устаревший domain key из runtime/API и добавил test-only systemd feature-flag
  drop-in для staff acceptance.
- 2026-07-14: v2.40 сделал десять основных KPI компактными и устойчивыми к
  разрыву чисел, закрепил адаптивную сетку 5/3/2 и ограниченные viewport
  подсказки при наведении и клавиатурном фокусе без изменения API и формул.
- 2026-07-14: v2.39 добавил в основной блок технические KPI `profitAfterTax` и
  `marginAfterTax`, закрепил десять KPI в сетке 5×2, nullable-маржу и
  корректный мост для ОСНО без повторного вычитания НДС и без распределения
  НДФЛ ИП по товарному P&L.
- 2026-07-14: v2.38 подробно описал в `Инструкции` работу с вкладкой
  `Проверки`: сводку, этапы, карточки источников, readiness-only проверку,
  сопоставление, обычное incremental-обновление, Ozon-only, редкую полную
  пересборку, обновление статуса и последующий разбор проблемных строк;
  contract test требует описание для каждого основного source-refresh action.
- 2026-07-14: v2.37 восстановил расходы WB после применения фильтров, выровняв
  корневой `kpis` endpoint `/rows` с `analytics.kpis`, и добавил справочный KPI
  `Итого к перечислению` как сумму сохранённых `forPaySum`; основной блок стал
  сеткой 5 финансовых + 3 операционных показателя.
- 2026-07-14: v2.36 добавил встроенную роль-зависимую страницу `Инструкция`,
  которая автоматически собирает актуальные названия разделов и действий из
  metadata живого интерфейса; contract test блокирует новые верхнеуровневые
  элементы без пользовательского пояснения.
- 2026-07-14: v2.35 упорядочил `Обзор` как KPI → аналитика → готовность,
  перенёс дополнительные KPI, доверие к данным и подробный контроль 1С в
  `Проверки`, добавил 1С-выручку вторичной строкой основной карточки выручки и
  явную подпись фактически загруженного месячного диапазона на графике.
- 2026-07-13: v2.34 made financial data-quality issues non-blocking for KPI and
  P&L calculation/display: available values remain visible with a preliminary
  warning while publication and client-recommendation gates remain unchanged.
- 2026-07-13: v2.33 reduced the overview to seven primary KPIs, grouped
  secondary and tax indicators into one disclosure, and replaced the compact
  money columns with a full-width accessible sales dynamics chart using only
  existing monthly facts.
- 2026-07-13: v2.32 introduced the analyst workspace shell, UI-only workspace
  fragments, one global filter context, a local missing-cost stepper and a
  compact read-only report context inside the existing AI overlay.
- 2026-07-13: v2.31 moved the full preflight quality-control panel above
  `Аналитика`, preserving its diagnostics, task board and problem-row action.
- 2026-07-11: v2.30 introduced canonical client-company aliases, a hard
  company/WB-cabinet integrity gate and report-scoped tax-profile readiness.
- 2026-07-11: v2.29 made lost-sales coverage and estimates follow the selected
  report dates/cabinet over the complete available WB provider window, with a
  versioned Decimal calculation context and no legacy-report inference.
- 2026-07-11: v2.28 defined bounded large-report aggregation, independent
  summary/freshness loading, explicit retry behavior and production timing
  gates without adding a materialized cache or increasing DB timeouts.
- 2026-07-11: v2.27 made loaded unresolved WB ↔ 1C mappings review-only for WB
  indicators and restored calculation over the complete available 92-day stock
  provider window without extrapolation.
- 2026-07-11: v2.26 allowed lost-sales calculation over the complete common WB
  provider window when it is shorter than the financial report period, with an
  explicit calculation period, boundary-week proration and no extrapolation.
- 2026-07-11: v2.25 made long 1C pagination heartbeat-safe, separated recent
  snapshot activity from a genuinely stalled background process and corrected
  `daily` UI wording so source refresh is not presented as report generation.
- 2026-07-11: v2.24 localized user-facing operational terminology throughout
  the cabinet while preserving internal source-refresh modes, statuses and API
  contract values.
- 2026-07-11: v2.23 moved source-refresh controls and progress out of
  `Интеграции` into the main `Данные и расчёт` panel before KPIs, with an
  independent status load and the explicit `Обновить и пересчитать` action.
- 2026-07-11: v2.22 moved the marketplace/1C mapping service out of the integrations
  widget; the main `Что разобрать первым` WB mapping card now opens the separate
  analyst queue filtered to WB, while client users retain the read-only row
  drilldown.
- 2026-07-11: v2.21 renamed the client-facing output action from `Текст для
  клиента` to `Отчёт для клиента` across the topbar, modal and status copy.
- 2026-07-10: v2.20 added semantic top-bar message colors and responsive action
  groups with a stable, visually secondary `Выход` position.
- 2026-07-10: v2.19 renamed the ambiguous client-output action to `Текст для
  клиента` and made the `AI-аналитик` top-bar action prominent with a robot
  icon.
- 2026-07-10: v2.18 replaced the ambiguous top-bar Excel action with a
  staff-only report-generation wizard for client, contour, period, readiness
  check, progress and protected current-Excel download.
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
