---
title: "Ozon integration changelog"
doc_type: changelog
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/marketplace-unit-economics-ozon-integration.md"
updated_at: "2026-07-21"
---

# Ozon integration changelog

Полная история изменений accepted Ozon integration spec. Текущие нормативные
требования остаются в
`docs/specs/marketplace-unit-economics-ozon-integration.md`; этот файл хранит
только хронологию изменений.

- 2026-07-21: Исключены приходные накладные `ВозвратОтКомиссионера` и
  документы с маркером отчета о выкупленных товарах из 1C-контроля расходов
  Ozon. Коллектор сохраняет `ВидОперации`, а неизвестная операция остается
  нераспределенной и требует проверки вместо автоматического признания
  расходом.

- 2026-07-21: Added composite 1C tax-profile settings from the periodic tax
  system and VAT registers for every linked organization; unsupported tax-base
  methods remain visible but uncalculated.

- 2026-07-20: accepted the pre-pilot correction set: exact raw response bytes
  with dual hashes, explicit report/pagination failures, signed quantity/COGS,
  missing-month blocking, global-only period expense fallback, fail-closed
  multi-account secrets and ozon-only 1C checkpoint resume.

- 2026-07-15: replaced production client names, report totals and snapshot ids
  with anonymized acceptance invariants; exact live evidence remains outside
  Git, while exported client labels use the accepted profit-before-NDFL
  semantics.

- 2026-07-12: Добавлен полный typed shadow для Ozon: cash-flow service lines,
  realization/posting, mutual settlement, buyout, B2B и product catalog
  материализуются из verified immutable files. Legacy DB rows и typed путь
  сравниваются по всем строкам, P&L, mart, mapping, выкупам и сверкам; порядок
  preview и технические row ids исключены из business grain.

- 2026-07-12: отчет комиссионера Ozon снова загружается с товарными частями;
  header-only snapshot помечается `partial_source` и не может заменить
  последний пригодный Ozon draft.

- 2026-07-12: Успешный production `ozon-only` создает staff-only Ozon draft,
  закрепленный за исходным refresh run. Добавлены mode-scoped статус загрузки,
  воспроизводимая сводка/Excel и явное разделение служебной витрины, черновика
  и опубликованного клиентского отчета.

- 2026-07-11: Разделены источники выручки Ozon: верхний факт берется только из
  регистра продаж 1C, а Ozon realization + buyout используются как ожидаемая
  первичка. Добавлен контроль отсутствующих, непроведенных, датированных не тем
  периодом и отличающихся по сумме документов с read-only перепроверкой после
  исправления в 1C.

- 2026-07-11: при отсутствии клиентского отчета контроль перед отправкой
  показывает состояние и диагностику Ozon + 1C вместо пустого блока загрузки.
- 2026-07-11: итоговый P&L Ozon приведен к прямому регистру продаж 1C и
  включает выкупы; SKU-детализация сохранена без искусственного распределения
  дополнительных документов по товарам.
- 2026-07-11: витрина Ozon сохраняет KPI и SKU-P&L без клиентского отчета;
  SKU-P&L явно отделен от верхних итогов регистра 1C, а себестоимость помечена
  как сумму, в которой НДС не выделен.
- 2026-07-11: верхние KPI Ozon переключены на прямые итоги регистра продаж 1C
  (включая выкупы); SKU-P&L сохранен отдельным и явно помечен как расчет без
  выкупов.
- 2026-07-11: made revenue coverage depend on unknown nonzero revenue rather
  than unmapped quantity, and marked nonpositive direct 1C COGS unavailable.
- 2026-07-11: Isolated direct 1C COGS control by counterparty inside Recorder
  and made unlabeled movements with multiple counterparties unavailable.
- 2026-07-11: Removed single-company/single-organization guessing, made
  documentless direct COGS control conservative, added unknown-revenue row
  counters and preserved the actually applied monthly materiality thresholds.
- 2026-07-10: Replaced the superseded whole-snapshot control with an anonymized
  closed-period control; added `costQuality`, materiality rules,
  `excludedIncompletePeriods` and the 1,000-row resumable snapshot-persistence
  requirement.
- 2026-07-10: Accepted canonical monthly Ozon P&L v2, organization-bound
  immutable tax profiles, audited overrides, open-period profit blocking,
  duplicate snapshot controls and deprecated legacy `pnl` isolation.
- 2026-07-10: Enforced project mapping service current decisions as the first
  Ozon mart mapping source and added reconciliation-only matching between the
  realization-report debit and an equal 1C service document without changing
  P&L expenses.
- 2026-07-09: Excluded Ozon realization nested
  `delivery_commission.standard_fee` / `return_commission.standard_fee` from
  direct SKU commission fields after live diagnostics showed they inflate Ozon
  commission; service acts remain period residual fallback.
- 2026-07-08: Grouped Ozon mart rows by seller `offer_id` before applying the
  one-1C-item-many-Ozon conflict rule, so internal Ozon `sku`/`product_id`
  variants do not block 1C revenue and COGS.
- 2026-07-08: Changed Ozon expense attribution priority: SKU-level
  realization/detail expenses are primary; mutual settlement is a period
  control; only positive unattributed residual is allocated by 1C revenue share.
- 2026-07-08: Added Finmodel 2.0 inspired Ozon article breakdown for mart v1:
  `articleRows` in the mart payload and per-SKU `expenseArticles`, while keeping
  Ozon/1C source boundaries and reconciliation visible.
- 2026-07-08: Added staff-only Ozon diagnostics Excel export and
  `articleDrilldown`: article-to-SKU allocations are separated from Ozon/1C
  reconciliation rows so unmatched 1C-only documents remain visible but do not
  affect SKU-profit.
- 2026-07-08: Added article-level expense reconciliation rows for 1C service
  documents without Ozon API pair in the selected month, including a visible
  hint to check adjacent mutual-settlement periods or separate Ozon service
  documents.
- 2026-07-08: Switched Ozon mapping priority from direct 1C marketplace
  extension reads to the project-owned marketplace/1C mapping service; 1C
  extension rows are candidate import only.
- 2026-07-08: Added Ozon mart auto-narrowing for ambiguous fallback article
  matches when exactly one 1C candidate is present in both commissioner revenue
  and period COGS; unresolved multi-candidate rows remain manual review.
- 2026-07-09: Excluded mutual settlement `Отчет о реализации` from period
  expenses so realization/control document amounts do not inflate Ozon
  commission and SKU profit.
- 2026-07-07: Added 1C `ИС_Маркетплейс 3.5.57.0` as the priority read-only
  Ozon mapping source and clarified Ozon mart as pre-tax.
- 2026-07-07: Corrected Ozon mart direct expense method after April 2026
  reconciliation with 1C supplier service documents: nested realization
  `standard_fee`/`amount`/`total` are not direct SKU expenses in V1 and must not
  be used for profit without separate 1C service-document allocation.
- 2026-07-07: Switched Ozon expense source of truth to Seller API
  cash-flow details and added 1C incoming invoice/service expense control as
  reconciliation, not as the primary expense source.
- 2026-07-07: Excluded positive `details.delivery.total` from Ozon expense
  adjustments; delivery remains visible for diagnostics but does not reduce V1
  marketplace expenses.
- 2026-07-07: Added expense reconciliation detail rows for Ozon API categories,
  top operation types and 1C control operations; clarified that period expenses
  are not automatically distributed to SKU rows.
- 2026-07-07: Added Ozon mutual settlement as a read-only monthly report source
  for expense article reconciliation before SKU allocation.
- 2026-07-07: Added Ozon V1 SKU allocation for mutual-settlement period
  expenses by 1C commissioner revenue share, with explicit
  `allocated_period_expense` row status and visible allocation basis.
- 2026-07-07: Switched Ozon P&L direct expense basis from cash-flow details to
  mutual settlement document rows after live April reconciliation showed mutual
  settlement matches 1C service/incoming documents, while cash-flow reflects a
  different money movement basis.
- 2026-07-07: Tightened Ozon diagnostics period filtering: monthly realization
  rows are matched to the selected period through collection manifest row
  ranges/page metadata so an April request does not include May pages with the
  same page index.
- 2026-07-07: Hardened Ozon mapping and snapshot metadata: generic
  `onec_marketplace_mapping` rows are accepted for Ozon only with explicit
  `marketplace=ozon`, and persisted Ozon technical metadata takes precedence
  over same-named fields in raw source rows.
- 2026-07-06: Added staff-only `Ozon Unit Economics Mart v1` contract and
  calculation rules: 1C commissioner SKU revenue, 1C COGS, SKU-level Ozon
  expenses, no auto-allocation, June as missing 1C close, buyout as separate
  reconciliation.
- 2026-07-06: Added Ozon buyout reconciliation rule: parse 1C expense invoices
  with `Выкуп`, extract buyout report number/period from comments, and compare
  against `ozon_products_buyout` without changing revenue basis.
- 2026-07-06: Added fallback Ozon buyout reconciliation by monthly period total
  when `ozon_products_buyout` has matching amount and quantity but does not
  expose the 1C buyout report number.
- 2026-07-06: Added final Ozon vs 1C revenue reconciliation formula and fixed
  buyout source counters to show API chunks, product rows, quantity and amount
  instead of a misleading zero row count.
- 2026-07-06: Removed Ozon cash-flow from the visible Ozon v1 vitrina and made
  1C sales register by Ozon counterparty the revenue basis.
- 2026-07-06: Added optional Ozon reconciliation collectors for posting
  realization, product buyouts and B2B sales JSON to explain 1C deltas without
  changing the revenue basis.
- 2026-07-06: Added Ozon issue vitrina requirements: status badge, first-action
  cards and accountant-owned mapping correction for `missing`/`ambiguous`.
- 2026-07-06: Added `Ozon v1` calculation vitrina requirements for 1C-based
  Ozon revenue, with explicit partial-source handling.
- 2026-07-06: Extended `ozon-only` source plan with Ozon realization and
  provisional 1C cost application when item-level rows, mapping and sales
  register cost are available.
- 2026-07-06: Fixed Ozon realization v2 request contract to send monthly
  `month`/`year` payloads instead of legacy `date` payloads.
- 2026-07-06: Treated missing current-month Ozon realization reports as
  `empty_expected` and exposed realization row-limit metadata in Ozon P&L.
- 2026-07-06: Connected web period filters to Ozon v1 1C sales-register totals.
- 2026-07-06: Moved Ozon diagnostics from the report detail tabs to a visible
  top-level client block so clients without a WB report still show Ozon + 1C
  readiness.
- 2026-07-05: Added staff-only Ozon + 1C diagnostics endpoint and web vitrina
  for latest `ozon-only` runs; preview is bounded and does not expose raw
  payloads, paths, hashes or credentials.
- 2026-07-05: Changed Ozon live-check away from `/v1/seller/info` to actual
  read-only source endpoints; added staff-only Ozon preview as the first web
  step before mixed marketplace reporting.
- 2026-07-03: Accepted V1 Ozon integration spec; added provider, source
  collectors, raw contracts and common marketplace snapshot contract.
