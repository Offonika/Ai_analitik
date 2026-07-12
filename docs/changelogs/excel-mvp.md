---
title: "Excel MVP changelog"
doc_type: changelog
domain: "marketplace-analytics"
audience: ["engineering", "consultant"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-unit-economics-excel-mvp-implementation.md"
updated_at: "2026-07-12"
---

# Excel MVP changelog

Полная история изменений accepted Excel MVP. Текущие правила реализации остаются
в `docs/specs/wb-unit-economics-excel-mvp-implementation.md`; этот файл нужен,
чтобы не перегружать implementation spec длинной хроникой.

- 2026-07-12 — added the audited Galustov management input-VAT scenario:
  import cost difference, WB services at 22/122 without penalties, actual
  purchase-book priority, explicit API/UI labels and a persistent review task.
- 2026-07-12 — split calendar 1C accounting KPIs from the WB product P&L:
  calendar quantity and COGS now include `ОтчетКомиссионера`, buyout
  `РасходнаяНакладная` and month-close cost adjustments, while `reportType=1`
  and `reportType=2` receive separate document-specific unit-cost layers.
- 2026-07-08 — changed `sku_mapping` source of truth from 1C marketplace
  extension/export to the project-owned marketplace/1C mapping service; old
  1C extension/TXT sources are candidate import or emergency fallback only.
- 2026-06-24 — clarified period semantics: `report_period` is selected by the
  generator/report_run, while WB/1C manifests describe `source_coverage`; old
  April-June and March-June dates are report revisions, not permanent product
  limits.
- 2026-06-24 — product framing renamed to `AI-аналитик отчетов`; this Excel MVP
  is fixed as the first factual layer of the Shumeyko WB/1C pilot.
- 2026-06-16 — accepted implementation spec created for Excel MVP.
- 2026-06-17 — added WB Finance detailed exporter, article mapping builder,
  provisional 1C cost extraction, and snapshot-to-Excel MVP command.
- 2026-06-17 — changed automatic mapping to product-level
  `nm_id + vendor_code -> 1C article` because one WB product can have several
  size-level SKUs/barcodes.
- 2026-06-17 — added explicit sales-register cost extraction path for
  gross-profit reconciliation.
- 2026-06-17 — accepted sales-register `Себестоимость` as the main COGS source
  with allocated extra costs already included; methodology version v2.
- 2026-06-17 — localized visible Excel statuses/comments and formatted main
  report sheets as Excel Tables with filters.
- 2026-06-17 — changed row quality priority so incomplete WB load does not hide
  missing mapping or missing cost statuses in Excel.
- 2026-06-17 — added 1C marketplace `Сопоставление товаров` TXT export as the
  primary mapping source when files exist under `data/onec_marketplace_mapping/`.
- 2026-06-17 — changed visible Excel WB cabinet labels to linked 1C organization
  names while keeping `WB_ACCOUNT_*` as internal snapshot identifiers.
- 2026-06-17 — added local Postgres raw/detail WB Finance persistence with
  JSONB payload retention and weekly aggregation view.
- 2026-06-17 — added Excel MVP build path that reads normalized WB snapshots
  from local Postgres instead of raw JSON files.
- 2026-06-17 — added local Postgres persistence for `sku_mapping` and
  `onec_unf_cost_snapshot` plus Excel build path that can read all calculation
  inputs from Postgres.
- 2026-06-17 — added WB report id propagation and Excel reconciliation sheet
  grouped by week and WB report number for finmodel fact checks.
- 2026-06-17 — added 1C-oriented report package reconciliation: commissioner
  reports vs WB buyout notices, plus product-level unit economics inside those
  packages; visible organization columns now use names instead of 1C keys.
- 2026-06-18 — changed sales-register COGS candidates from whole-period
  weighted average to weekly effective cost, added stable Excel output path,
  replace-snapshot loading, and separate 1C gross-profit vs WB-expense profit
  columns for reconciliation.
- 2026-06-18 — added direct `Валовая прибыль 1С` Excel sheet from
  `AccumulationRegister_Продажи` and limited WB COGS extraction to marketplace
  counterparties with commissioner reports.
- 2026-06-18 — split WB `deduction/deductionSum` into separate
  `WB Продвижение`, added weekly `sales-reports/list` snapshot support, and
  added Excel sheets `Сводный отчет WB` and `Сверка услуг WB`.
- 2026-06-18 — added WB read-only detailed export by weekly `reportId`, a
  top control block for WB service reconciliation, Excel sheet
  `Расшифровка услуг 1С`, and client-facing sheet `Юнит экономика`.
- 2026-06-21 — added `Номер отчета WB` and `Дата отчета WB` to
  `unit_economics_report`, Excel sheet `Юнит экономика`, and web summary rows.
- 2026-06-21 — added client-facing `Документ-отчет` to the
  `Юнит экономика` sheet, web payload, API row filters, and cabinet UI for
  WB-to-1C comparison by report package.
- 2026-06-21 — split `Юнит экономика` product rows by 1C report package so
  commissioner reports and WB buyout notices do not mix in one
  `Документ-отчет` filter value.
- 2026-06-21 — added PDF-formula control fields from WB `sales-reports/list` to
  `Сверка с 1С`: realized amount, goods sold amount, loyalty discount
  compensation, payout to seller, and deltas against MVP detail totals.
- 2026-06-21 — added Excel sheet `Сверка документов 1С` to compare expected WB
  report packages with actual `ОтчетКомиссионера` and `РасходнаяНакладная`
  documents loaded into 1С by quantity, amount, date and document type.
- 2026-06-21 — made Excel sheet `Сверка документов 1С` visible by default,
  because it is a user-facing control for manual WB-to-1C document diagnostics.
- 2026-06-21 — added `К перечислению` document-level control on
  `Сверка документов 1С`: WB `forPaySum` is shown separately from document
  revenue and compared with 1C `Итого взаиморасчетов` when that read-only field
  is present in the 1C export.
- 2026-06-21 — changed the 1C source for `Итого взаиморасчетов`: document
  settlement totals are loaded from `РасчетыСПокупателями` and
  `РасчетыСПоставщиками`, not from `AccumulationRegister_Продажи`.
- 2026-06-21 — added read-only 1C document-header matching for
  `ОтчетКомиссионера` and `РасходнаяНакладная`: WB report ids are taken from
  the incoming document number or buyout-notice comment and used before the
  older week-based fallback.
- 2026-06-21 — added web-cabinet unit-economics period filters:
  `period_start` and `period_end` filter product rows by weekly period.
- 2026-06-21 — added web-cabinet document reconciliation payload and UI tab:
  `Сверка документов 1С` rows are imported into the report API with
  `WB к перечислению (forPaySum)`, `1С итого взаиморасчетов`, quantity/amount
  deltas, document ids and statuses for document-level WB-to-1C diagnostics.
- 2026-06-21 — split document reconciliation quantities into sales, returns and
  net quantity for both WB and 1C, changed `К перечислению` to a separate payout
  status that does not compare WB `forPaySum` with 1C settlement turnover, and
  added automatic 1C marketplace service sample pickup with nomenclature-based
  service classification.
- 2026-06-22 — added explicit weekly buyout report controls to
  `Сверка документов 1С`: `WB отчет продаж`, `WB отчет выкупов`, buyout
  `retailAmountSum`, `forPaySum`, `bankPaymentSum`, 1C expense invoice amount,
  and buyout deltas for analyst review.
- 2026-06-22 — clarified buyout amount semantics: 1C expense invoice amount is
  treated as the paper buyout notice net amount, while WB API buyout totals are
  diagnostic controls and do not make the document amount status fail.
- 2026-06-22 — constrained sales-register COGS unit-cost aggregation by 1C
  document before weekly averaging: zero-quantity cost rows are still paired
  with their own document, but amount-only rows from other documents no longer
  inflate a WB report package unit cost.
- 2026-06-23 — changed monthly `Сверка с 1С ОПиУ` COGS grouping to the actual
  matched 1C document date for both `Товары по отчетам 1С` and
  `Валовая прибыль 1С`; OPIU remains a reference layer for marketplace expenses
  and no longer drives the main product COGS control.
- 2026-06-23 — relaxed the dashboard profitable-products block from strict `ОК`
  rows to profitable rows with positive 1C cost and non-blocking warning
  statuses; the dashboard now shows `Статус данных` in that block so warnings
  remain visible instead of making the section blank.
- 2026-06-18 — changed local Excel and calculation-input builds to auto-use the
  latest available 1C sales register as the primary COGS source before falling
  back to provisional receipt costs.
- 2026-06-18 — added controlled allocation for `Хранение` and `WB Продвижение`:
  product rows are scaled to weekly WB Finance report totals and audited on
  Excel sheet `Распределение расходов`.
- 2026-06-18 — added read-only WB paid storage and promotion stats snapshots as
  product-level allocation bases for `Хранение` and `WB Продвижение`; weekly WB
  financial report remains the control total.
- 2026-06-18 — added product-level tax layer: VAT 5% is extracted from revenue
  as `5/105`, USN 1% is allocated by revenue, and other OPIU variable expenses
  remain deferred until separate allocation rules are accepted.
- 2026-06-18 — simplified client workbook UX: the main unit-economics sheet uses
  Russian business terms, shows storage, promotion, VAT, USN and after-tax
  profit next to each product, and hides technical reconciliation sheets by
  default.
- 2026-06-18 — fixed no-SKU WB expense handling for `Хранение` and
  `WB Продвижение`: expense-only rows are allocated to product rows by product
  detail or revenue; the main client sheet is built from the product calculation
  view and does not show these technical rows as `Товар не определен`.
- 2026-06-18 — improved client UX: added visible `Дашборд`, split identifiers
  into `nmId WB`, `Артикул WB`, `Артикул 1С` and `Баркод`, added a
  plain-language reason for each data status, and added conditional formatting
  for profit, margin, data-quality statuses, storage and promotion. The
  experimental `Сводные` sheet is removed from the client workbook until its
  format is accepted.
- 2026-06-18 — changed missing-week COGS handling: if exact weekly sales-register
  cost is absent, the calculation uses the nearest available 1C cost for the
  same item and marks the row as `needs_review` for month-close reconciliation.
- 2026-06-18 — added client-facing return analytics: `UnitEconomicsRow` now
  carries sales quantity, return quantity, return amount and return rate; Excel
  shows these fields on `Дашборд`, `Юнит экономика` and visible `Возвраты`, and
  the loss table uses deterministic loss reasons without inventing return
  reasons.
- 2026-06-18 — changed the operational report period to follow the selected WB
  Finance manifest (`2026-03-01` — `2026-06-17` for the current snapshot) and
  changed local workbook builds to choose the latest snapshot directory by
  modification time instead of lexicographic name, so diagnostic weekly folders
  do not override the full-period export.
- 2026-06-18 — changed the current client-facing report period to
  `2026-04-01` — `2026-06-17`, added month-to-month dynamics, visible expense
  structure with revenue shares, return barcodes, loss classification and a
  planned out-of-stock lost-sales analytics section.
- 2026-06-18 — added read-only WB current warehouse remains snapshot export;
  historical lost-sales calculation remains deferred until daily WB stock
  history/slices and 1C commissioner-stock reconciliation are accepted.
- 2026-06-18 — added read-only WB `STOCK_HISTORY_DAILY_CSV` export for
  `2026-04-01` — `2026-06-17`; it stores historical daily stock ZIP/CSV
  snapshots for later out-of-stock lost-sales calculation.
- 2026-06-18 — added visible Excel sheet `Упущенные продажи` and DOCX/Markdown
  report block with a preliminary out-of-stock estimate based on WB
  `STOCK_HISTORY_DAILY_CSV`, sales velocity and after-tax unit economics.
- 2026-06-19 — changed the client default period to `2026-03-01` —
  `2026-06-17`, added СПП metrics from WB `cashbackDiscountSum`, renamed the
  client profit metric to `Маржинальный доход WB после налогов`, added visible
  `Сверка с 1С ОПиУ`, and documented the Power Query / Power BI export path
  through calculated marts rather than raw snapshots.
- 2026-06-23 — added client-requested own/1C warehouse stock columns to
  `Упущенные продажи`: the sheet now shows `Остаток 1С на складах, шт` and
  `Склады 1С с остатком`, and positive stock changes the management conclusion
  toward moving stock to WB while keeping lost profit a preliminary estimate.
- 2026-06-23 — added client-facing `Ликвидность МД` as a deterministic
  monthly assortment-liquidity mart over existing unit rows: the accepted metric
  remains after-tax WB marginal income, while МД1-МД6 is shown as a diagnostic
  cascade with data-quality status kept visible; final МД totals are reconciled
  to the accepted `Юнит экономика` row totals to avoid rounding drift.
