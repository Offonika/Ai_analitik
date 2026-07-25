---
spec_id: "workspace-shumeyko-partners-wb-logistics-cost-analysis-implementation"
title: "WB: анализ затрат на логистику"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "consultant", "client"]
source_of_truth: true
truth_scope: logistics-cost-analysis
truth_priority: 100
related_code: [src/wb_unit_economics/logistics_analysis.py, src/wb_unit_economics/return_reason_analysis.py, src/wb_unit_economics/wb_goods_return.py, src/wb_unit_economics/wb_return_claims.py, src/wb_unit_economics/wb_tariffs.py, src/wb_unit_economics/wb_supplier_sales.py, src/wb_unit_economics/wb_finance.py, src/wb_unit_economics/postgres_finance.py, src/wb_unit_economics/client_report.py, src/wb_unit_economics/web/models.py, src/wb_unit_economics/web/repository.py, src/wb_unit_economics/web/report_scope.py, src/wb_unit_economics/web/source_refresh.py, src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/ai.py, src/wb_unit_economics/web/settings.py, src/wb_unit_economics/web/static/index.html, src/wb_unit_economics/web/static/app.js, src/wb_unit_economics/web/static/styles.css, sql/postgres_schema.sql, scripts/profile_wb_logistics_readiness.py, scripts/probe_wb_logistics_factors.py, deploy/systemd/shumeiko-web-test.service.d/zz-logistics-r5-return-reasons.conf, deploy/systemd/shumeiko-web-test.service.d/zzz-logistics-r6-client-test.conf]
related_tests: [tests/test_logistics_analysis.py, tests/test_return_reason_analysis.py, tests/test_wb_goods_return.py, tests/test_wb_return_claims.py, tests/test_probe_wb_logistics_factors.py, tests/test_wb_tariffs.py, tests/test_wb_supplier_sales.py, tests/test_wb_finance.py, tests/test_postgres_finance.py, tests/test_profile_wb_logistics_readiness.py, tests/test_report_marts.py, tests/test_logistics_factor_marts.py, tests/test_source_refresh.py, tests/test_web_app.py, tests/test_ai_analyst.py, tests/test_client_report.py, tests/test_runtime_contour_scripts.py]
contracts: [wb_api_snapshot, unit_economics_report, ai_analysis_summary]
ai_sections:
  status: "Статус документа"
  goal: "Цель"
  terms: "Термины и обязательные трактовки"
  scope: "Scope"
  sources: "Источники и границы чтения"
  data_gate: "Техническая проверка данных перед реализацией"
  calculation: "Расчетная модель"
  marts: "Расчетные витрины"
  api: "API"
  interface: "Интерфейс"
  recommendations: "Правила рекомендаций"
  acceptance: "Acceptance Criteria"
  tests: "Test Plan"
code_anchors:
  - path: src/wb_unit_economics/logistics_analysis.py
    symbols: ["def resolve_logistics_period", "def build_logistics_analysis", "def build_order_rows", "def build_sku_rows", "def build_tariff_rows", "def build_route_rows"]
  - path: src/wb_unit_economics/return_reason_analysis.py
    symbols: ["class ReturnReasonMartRow", "class ReturnReasonAnalysisContext", "def build_return_reason_analysis"]
  - path: src/wb_unit_economics/web/repository.py
    symbols: ["def replace_report_logistics_analysis", "def report_logistics_summary_payload", "def report_logistics_analysis_payload", "def build_logistics_insight", "def replace_report_logistics_tariff_analysis", "def report_logistics_tariffs_payload", "def replace_report_logistics_route_analysis", "def report_logistics_routes_payload", "def replace_report_logistics_return_reason_analysis", "def report_logistics_return_reasons_payload", "def _logistics_context_state", "def _logistics_recommendations"]
  - path: src/wb_unit_economics/web/source_refresh.py
    symbols: ["def _build_and_persist_logistics_analysis", "def _record_wb_goods_return", "def _select_goods_return_snapshot", "def _record_wb_return_claims", "def _select_return_claims_snapshot", "def _build_and_persist_logistics_return_reasons", "def _build_and_persist_logistics_tariffs", "def _select_tariff_snapshot", "def _build_and_persist_logistics_routes", "def _select_route_snapshot"]
  - path: src/wb_unit_economics/wb_goods_return.py
    symbols: ["def normalize_goods_return_source_row", "def build_goods_return_links"]
  - path: src/wb_unit_economics/wb_return_claims.py
    symbols: ["def export_wb_return_claims", "def normalize_claim_source_row", "def build_return_claim_links"]
  - path: scripts/probe_wb_logistics_factors.py
    symbols: ["def fetch_r0_source_payload", "def run_r0_identity_probe"]
  - path: src/wb_unit_economics/web/settings.py
    symbols: ["logistics_analysis_enabled: bool", "logistics_analysis_client_enabled: bool", "logistics_tariffs_enabled: bool", "logistics_tariffs_client_enabled: bool", "logistics_routes_enabled: bool", "logistics_routes_client_enabled: bool", "logistics_return_reasons_enabled: bool", "logistics_return_reasons_client_enabled: bool"]
  - path: src/wb_unit_economics/web/static/app.js
    symbols: ["function loadLogisticsAnalysis", "function renderLogisticsWorkspace", "function renderLogisticsInsight", "function loadLogisticsReturnReasons", "function renderLogisticsReturnReasons", "function logisticsReturnReasonsAvailable"]
test_anchors:
  - path: tests/test_return_reason_analysis.py
    symbols: ["def test_builds_exact_safe_return_reason_row", "def test_denied_claims_is_partial_not_blocking_and_keeps_reason_fact", "def test_multiple_return_segments_collapse_to_latest_finance_date"]
  - path: tests/test_logistics_analysis.py
    symbols: ["def test_closed_week_period_keeps_both_partial_boundaries_separate", "def test_closed_week_period_without_full_week_is_only_partial", "def test_builds_reconciled_order_and_sku_marts_with_low_sample", "def test_missing_profit_link_keeps_financial_kpis_null", "def test_sku_link_normalizes_all_string_dimensions", "def test_partial_boundary_week_uses_exact_source_but_full_week_uses_report", "def test_not_applicable_financial_link_uses_fbo_report_alias_only"]
  - path: tests/test_source_refresh.py
    symbols: ["def test_logistics_analysis_is_built_from_persisted_read_only_snapshot", "def test_logistics_analysis_reads_verified_file_authoritative_snapshot", "def test_goods_return_snapshot_db_and_file_authoritative_are_equivalent", "def test_goods_return_snapshot_integrity_failures_are_blocking", "def test_return_reason_context_builds_from_lineage_and_denied_claims_is_partial", "def test_route_snapshot_db_and_file_authoritative_are_equivalent", "def test_route_snapshot_integrity_failures_are_blocking", "def test_route_context_and_rows_are_built_for_new_draft"]
  - path: tests/test_wb_goods_return.py
    symbols: ["def test_goods_return_link_uses_finance_srid_and_one_canonical_return_chain", "def test_goods_return_link_rejects_cross_field_scope_and_chain_ambiguity"]
  - path: tests/test_wb_return_claims.py
    symbols: ["def test_export_marks_confirmed_empty_without_blocking", "def test_export_marks_access_denied_without_creating_snapshot_files", "def test_exact_match_activates_claim_flags_and_empty_rows_do_not"]
  - path: tests/test_probe_wb_logistics_factors.py
    symbols: ["def test_claims_fetch_reconciles_all_pages_without_exposing_raw_values", "def test_run_r0_identity_probe_uses_all_claim_pages_and_keeps_r2_fail_soft"]
  - path: tests/test_web_app.py
    symbols: ["def test_logistics_api_returns_reconciled_safe_staff_payload", "def test_logistics_missing_profit_link_fails_financial_slice_closed", "def test_logistics_products_filter_returns_only_missing_profit_links", "def test_logistics_recommendation_uses_full_slice_not_by_total_top_ten", "def test_logistics_routes_api_partial_coverage_uses_full_filtered_slice", "def test_logistics_routes_role_and_flag_matrix", "def test_required_route_context_controls_publication_readiness", "def test_logistics_return_reasons_api_states_filters_and_safe_payload", "def test_logistics_return_reasons_role_and_flag_matrix", "def test_required_return_reason_context_controls_publication_readiness", "def test_source_refresh_latest_exposes_safe_return_claims_marker", "def test_cabinet_static_assets_use_readiness_api_and_safe_rendering", "def test_multi_client_report_access_requires_explicit_client"]
  - path: tests/test_ai_analyst.py
    symbols: ["def test_ai_logistics_digest_excludes_external_ids_and_raw_lineage", "def test_ai_logistics_uses_requested_period_from_current_screen"]
  - path: tests/test_client_report.py
    symbols: ["def test_client_report_uses_same_logistics_insight_without_zero_substitution", "def test_client_report_docx_preserves_source_and_content"]
  - path: tests/test_runtime_contour_scripts.py
    symbols: ["def test_r5_test_drop_in_keeps_return_reasons_staff_only", "def test_r6_test_drop_in_enables_all_logistics_for_client_role"]
depends_on: [workspace-shumeyko-partners-wb-unit-economics-excel-mvp-implementation, workspace-shumeyko-partners-wb-unit-economics-db-first-report-marts, workspace-shumeyko-partners-wb-unit-economics-ai-web-cabinet-implementation]
rollout_required: true
updated_at: "2026-07-25"
---

# Статус документа

Статус — `accepted`. Шесть бизнес-решений по составу MVP, классификации,
минимальной выборке, отображению влияния на прибыль, историческим данным и
очередности Excel согласованы 16 июля 2026 года.

`Accepted` означает утвержденную цель реализации, но не подтверждает production
rollout или завершение всех очередей. Первая очередь v5 и подпакеты факторов
F-1…F-5 прошли отдельные staff-only test acceptance на immutable report runs.
R-6 client-role ранее был отдельно принят только на test, но свежая
операционная проверка 25 июля 2026 года подтвердила его фактический rollback:
client login и все client-флаги F-1…F-5 выключены, а master-флаги остаются
staff-only. Production rollout не выполнен. Подчинённый F-5 spec переведён в
`implemented`; третья очередь и production-решение остаются незавершёнными.

# Текущее состояние реализации

В текущем change set реализованы hardening-версия методики
`wb-logistics-v6`, ключ `wb-order-product-v1`, классификатор
`wb-logistics-classifier-v1`, неизменяемые витрины order/SKU, многомерный
reconciliation до действующего `ReportUnitRow`, три read-only API,
детерминированные рекомендации и безопасный агрегатный контекст для AI.
Вложенный маршрут `#tables/logistics`, answer-first порядок, trust strip и
раздельные состояния реализованы и приняты на test. Контексты
`wb-logistics-v1`–`wb-logistics-v4`, несовместимая версия ключа и старый отчет
без контекста возвращают `needs_rebuild`.

Defaults в коде для `SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED` и
`SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED` — `false/false`; это не описание
фактического состояния сред. Последнее записанное operational evidence и
обязательные команды повторной проверки находятся в
[`docs/runbooks/wb-logistics-v4-continuation.md`](../runbooks/wb-logistics-v4-continuation.md).
Factor client rollout разрешён и принят только на test; production flags
остаются неизменными до отдельного согласования. F-1…F-4 сначала были приняты
на staff-only test. Для F-5 принят отдельный контракт причин возвратов. После закрытого R-0I
и R-0L отдельно разрешённый production full source refresh создал новый
неопубликованный immutable draft: Finance загружен в verified
file-authoritative storage без DB-строк и ambiguity, logistics context имеет
`ready`, опубликованный current report и feature flags не изменены.

Повторный boolean-only R-0I на новом lineage подтвердил exact
`goods-return.srid → Finance.srid` и однозначное разрешение в canonical return
chain (`goodsReturnIdentityGate=true`). Baseline `srid → orderUid` не совпал, а
в текущем claims window source keys отсутствуют (`claimsIdentityGate=false`).
Поэтому `completeIdentityGate=false` и общий `implementationGate=false`.
Пользователь отдельно принял source-specific контракт R-1: exact
`goods-return.srid → Finance.srid` с tenant/client/cabinet/nm scope и одной
canonical return chain; `goodsReturnImplementationGate=true`, исторический
`contractChangeRequired=true` закрыт этим решением. 23 июля пользователь принял
fail-soft R-2: пустой claims window и закрытый scope становятся явными
per-cabinet source states, но не блокируют реализацию, основную логистику или
публикацию. Конкретный `claimAvailable=true` разрешён только по exact
`(tenant, client, cabinet, nm_id, claims.srid → Finance.srid)` и одной
canonical return chain; после появления доступа такой match активируется
автоматически.
R-1 влит в `main` через PR №56: registered immutable source,
DB/file-authoritative selector, normalization и internal exact link/coverage;
mart/API/UI и environment rollout не выполнялись. Claims active/archive
provider-total pagination hardened в PR №57. Отдельно разрешённый live R-0I из
`main@0deacf4` подтвердил schema и полную pagination без mismatch, но доступный
claims scope пуст, а другой scope закрыт по доступу; source keys отсутствуют,
`claimsIdentityGate=false`. Это ограничивает текущее покрытие, но по принятому
fail-soft контракту больше не закрывает R-2. Test-only full preflight остановлен
выключенным source-refresh master; dry-run дал `needs_review` без нового report,
фактический refresh и transient override не выполнялись.

R-2 влит в `main` через PR №59, R-3 — через PR №60, R-4 — через PR №61. R-3
сохраняет одну
безопасную mart-строку на canonical Finance return chain, последнюю
подтверждённую Finance return date при нескольких segments, additive
`report_logistics_return_reason_contexts/rows`, draft-only atomic persistence,
readiness и read-only `/logistics/return-reasons` с SQL-фильтрами,
сортировками, пагинацией и coverage полного среза. Empty/denied/unmatched
claims остаются `partial/data_unavailable` и не блокируют основную логистику
или публикацию. R-4 добавил coverage-first UI, который
показывает три состояния покрытия, безопасные source rows и только
подтверждённые рекомендации, скрывается и не делает request при выключенном
флаге, превращает таблицу в mobile-карточки.

R-5 staff-only test acceptance завершён на immutable
`main@a9ec18c`, `sourceDirty=false`. Additive schema применена, tracked
test drop-in включает F-1…F-5 только для staff и явно оставляет все
client-флаги `false`. Новый full refresh создал неопубликованный
`needs_review` draft: return-reasons context имеет `partial`, blocking reasons
пусты, Finance chains и mart/context reconciliation присутствуют. Staff API,
SQL-сортировка/пагинация и browser QA 1440×900/390×844 пройдены; client API
возвращает 404, секция скрыта и request не выполняется. Production runtime,
published current report и client flags не менялись.

R-6 client-role rollout был завершён только на test и прошёл role/tenant/PII
acceptance, но больше не описывает фактическую среду. На 25 июля 2026 года
effective test-конфигурация снова staff-only: установлен более ранний
staff-only drop-in, client login выключен, master-флаги F-1…F-5 включены, а
client-флаги F-1…F-5 выключены. После отдельного решения пользователя
25 июля 2026 года готовый отчет по методике `wb-logistics-v6` опубликован как
текущий на test: базовый logistics context имеет `ready`, contexts F-1…F-5 —
явный `partial`; активный source refresh отсутствует. Клиентская роль не должна
видеть сценарий логистики. Production runtime/report не требуют logistics
contexts, и production-флаги логистики не включены.
Excel и калькуляторы в этот пакет не входят.

Следующий принятый presentation-layer пакет не меняет методику v6 и
immutable marts. Он вводит контракт `wb-logistics-insight-v1`: staff-интерфейс,
AI и аналитический документ используют один детерминированный вывод по полным
закрытым неделям, а неполные границы показывают отдельным фактическим блоком
без финансовых KPI. Пакет не требует source refresh, DB migration или
пересборки report run и разворачивается только на staff-only test.

# Цель

Добавить в web-кабинет вложенный сценарий `Аналитика и таблицы -> Логистика`,
который
отвечает на четыре практических вопроса:

1. сколько компания фактически потратила на логистику и какова ее доля в
   выручке;
2. какие товары создают максимальные расходы и сильнее всего снижают прибыль;
3. какие подтвержденные факторы связаны с высокой стоимостью;
4. какие действия следует проверить в первую очередь.

После приемки фактического блока предусматриваются два read-only калькулятора:
логистики и маржинального дохода на единицу товара.

# Бизнес-результат

Пользователь должен видеть не отдельные строки финансовой детализации WB, а
понятную последовательность:

```text
общая сумма -> проблемные товары -> подтвержденные факторы
-> детализация до заказа -> рекомендуемое действие
```

Каждая сумма и вывод должны быть воспроизводимы из сохраненных снимков и
привязаны к конкретному `report_id`.

# Термины и обязательные трактовки

- `Фактическая логистика` — признанный в финансовой детализации WB расход,
  нормализованный по действующей методике отчета.
- `Прямая логистика` — часть фактической логистики, классифицированная как
  движение товара к покупателю.
- `Обратная логистика` — часть фактической логистики, классифицированная как
  возвратное движение.
- `Корректировки логистики` — перерасчеты и отдельные логистические операции,
  которые нельзя повторно включать в прямую или обратную часть.
- `Цепочка заказа` — связанные финансовые строки одного заказа и товара.
  Версия `wb-order-product-v1` — SHA-256 от версии, tenant, клиента, кабинета,
  `orderUid` и товара (`nmId`, резервно `sku`). `srid` не используется как
  fallback. Одинаковый raw `orderUid` в разных кабинетах разрешен; коллизией
  является только совпавший итоговый hash для разных составных идентичностей.
  `rrdId` является идентификатором строки, а не всего заказа.
- `Факт` — значение из финансовой детализации или другой сохраненной записи WB.
- `Оценка` — сценарный расчет по тарифу и введенным параметрам. Оценка никогда
  не подменяет факт.
- `Гипотеза` — возможное объяснение, которое нельзя подтвердить доступными
  данными.

Строка с операцией логистики сама по себе не доказывает невыкуп или возврат.
Статус определяется по всей доступной цепочке заказа и зафиксированному
классификатору операций.

# Scope

## Первая очередь: фактический MVP

Состав первой очереди согласован и обязателен:

- сводные показатели логистики;
- динамика по периодам;
- рейтинги товаров по сумме затрат и доле в выручке;
- выделение возвратной логистики там, где направление подтверждено;
- влияние логистики на прибыль товара;
- детализация до цепочки заказа;
- явные статусы полноты и качества данных;
- список действий на основе рассчитанных правил;
- использование действующих фильтров кабинета;
- read-only AI-пояснение уже рассчитанных фактов.

Excel-экспорт этого блока не входит в первую очередь. Он добавляется только
после приемки расчетов и интерфейса web-MVP.

## Вторая очередь: факторы затрат

Входит после проверки доступности источников:

- заявленные габариты товара вместе с упаковкой;
- контрольные замеры WB и расхождения;
- коэффициенты, периоды их действия и отдельные штрафы;
- склад отправления и доступное направление доставки;
- агрегаты по складам и маршрутам;
- разделение подтвержденной причины, гипотезы и отсутствующих данных.

## Третья очередь: калькуляторы

Входит:

- сценарный калькулятор логистики;
- сценарный калькулятор маржинального дохода на единицу;
- сравнение факта и сценария;
- предзаполнение параметров из выбранного товара с возможностью ручной замены;
- отсутствие любых изменений в WB или 1С.

# Out Of Scope

- изменение карточек товаров, цен, поставок или остатков в WB;
- запись в 1С, банк, CRM, Telegram, email или Bitrix;
- автоматическое изменение распределения товара по складам;
- придумывание причин возврата, которых нет в источнике;
- трактовка `Микс` или `Моно` как доказательства размера транспортной упаковки;
- трактовка отрицательного коэффициента вознаграждения WB как самостоятельного
  доказательства убыточности товара;
- использование разницы между ценой до скидки и оплатой покупателя как
  автоматического убытка продавца;
- публикация raw-строк, внутренних идентификаторов, токенов или клиентских
  выгрузок через открытый API;
- Ozon в первой версии. Расширение на другие маркетплейсы требует отдельного
  согласования методики и источников.

# Источники и границы чтения

## Обязательные источники первой очереди

1. Сохраненная финансовая детализация WB — итоговый факт расходов, операций и
   денежных корректировок.
2. Текущий DB-first `unit_economics_report` — выручка, прибыль, количество
   продаж и действующая классификация расходов.
3. Сохраненный raw snapshot — доказательная база и возможность повторного
   расчета после изменения классификатора.

`wb-logistics-v6` выбирает финансовую детализацию независимо от физического
способа хранения raw snapshot. Если строки сохранены в `source_snapshot_rows`,
используется DB-authoritative reader. Если collection явно помечена
`file_authoritative` или `skipped_large_snapshot` с
`rawFilesAuthoritative=true`, используется file-authoritative reader: только
после повторной проверки `rawIntegrity=verified`, manifest/hash/row count и
границы пути внутри зарегистрированного `raw_path`. Файлы читаются по одной
странице, без загрузки всего snapshot в память.

Для одного refresh-run допустим ровно один authoritative reader. Одновременное
наличие DB-строк и file-authoritative статуса, небезопасный путь, отсутствующий
файл, несовпадение manifest/hash/row count или нераспознанный persistence status
блокируют gate с обезличенным кодом ошибки. Канонический source row id, row hash,
revision precedence и input hash не зависят от storage backend: одинаковый
immutable snapshot обязан давать тот же результат и hash. Старый report run не
дополняется на месте; recovery или повторный расчет всегда создает новый draft.

Операционные данные о заказах могут использоваться для дополнительного
контекста, но не должны заменять итоговую финансовую детализацию.

## Дополнительные источники второй очереди

- карточки товаров с габаритами и весом вместе с упаковкой;
- отчеты WB о замерах и штрафах за расхождение габаритов;
- доступные поля склада и направления доставки;
- тарифы WB для сценарного расчета.

Тариф, действующий сегодня, не является доказательством стоимости исторического
заказа. Для исторического объяснения используется только тариф или коэффициент,
привязанный к соответствующему периоду, либо вывод помечается как оценка.

## Read-only boundary

Коннекторы читают данные по минимально необходимым правам. Новые write-capable
операции во внешние системы запрещены. Внутренние снимки, витрины, audit и
служебные статусы сохраняются по действующим правилам tenant isolation и
retention.

# Техническая проверка данных перед реализацией

До изменения расчетного и web-кода необходимо на тестовом отчете без публикации
raw данных подтвердить:

- долю финансовых строк со стабильным идентификатором заказа;
- возможность связать продажу, логистику, возврат и корректировку без
  дублирования;
- доступность склада и направления доставки за нужный исторический период;
- наличие необходимых категорий доступа WB для финансов, карточек и замеров;
- корректность классификации минимум на нескольких типовых цепочках;
- возможность сверить результат с текущей суммой логистики отчета.

Если источник не передает нужное поле, оно получает статус `missing` и не
заменяется нулем, догадкой или текущим тарифом.

## Исторический результат этапа 0 на 16 июля 2026 года

> Исторический диагностический артефакт. Он не определяет текущий gate или
> rollout. Последнее записанное состояние сред находится в operational runbook
> [`docs/runbooks/wb-logistics-v4-continuation.md`](../runbooks/wb-logistics-v4-continuation.md)
> и должно быть повторно проверено командами из него перед operational-выводом.

Проверка выполнена read-only профилировщиком на репрезентативном локальном
снимке. Профиль содержит только агрегаты покрытия и качества, без raw-строк,
товаров, внешних идентификаторов и денежных сумм.

```bash
.venv/bin/python scripts/profile_wb_logistics_readiness.py SNAPSHOT_DIR
```

Матрица готовности:

| Область | Статус | Вывод |
|---|---|---|
| Фактическая сумма логистики | `ready` | `deliveryService` доступно и проходит числовую проверку. |
| Направление операции | `ready_for_classifier` | На проверенном снимке логистические строки имеют явный сигнал `deliveryAmount` или `returnAmount`; правило еще требуется закрепить версионированным классификатором. |
| Ключ цепочки | `blocked_by_collision` | `orderUid` и `srid` имеют хорошее покрытие, но встречаются у нескольких товаров. Использовать любой из них как единственный ключ запрещено. |
| Дополнительные идентификаторы | `needs_fresh_snapshot` | В старом наборе запрошенных полей отсутствовали `orderId`, `shkId` и `stickerId`; сбор расширен, результат нужно повторно профилировать. |
| Склад отправления | `ready_with_coverage` | `officeName` доступно почти для всех логистических строк; пропуски сохраняются как `missing`. |
| Направление и тарифные факторы | `needs_fresh_snapshot` | `country`, ПВЗ, `dlvPrc`, период фиксированного тарифа и тип короба добавлены в raw-контракт, но не подтверждены новым снимком. |
| Текущие расчетные витрины | `not_ready` | Действующая дневная агрегация теряет order-level зерно и не подходит для восстановления цепочек. |
| Габариты и замеры | `phase_2_gap` | Габариты есть в raw-карточках, но пока не сохраняются в плоском слое; отдельные источники контрольных замеров и штрафов не подключены. |

Исторический профиль выше объясняет исходные ограничения и не является
разрешением на rollout. В `wb-logistics-v6` технический gate перед созданием
order/SKU-витрин выполняется автоматически:

1. получить новый read-only снимок с расширенным набором полей;
2. повторить профиль отдельно по каждому кабинету;
3. подтвердить 100% обязательных дат, чисел, кабинетов, организаций, схем,
   `orderUid` и товаров как в WB-источнике, так и в `ReportUnitRow`; значения
   `missing`/`invalid` не заменяются нулем, началом периода или `FBO`. Два
   согласованных исключения описаны ниже: схема `not_applicable` у операции
   `Коррекция логистики` и финансовая строка с явной нулевой логистикой без
   `orderUid`;
4. сверить логистику по неделе, кабинету, организации, схеме и товару с
   допуском не более `0,01 ₽` до и после построения order/SKU-витрин;
5. блокировать цепочку `заказ–товар–день`, если внутри нее различаются
   организация или схема FBO/FBS;
6. при любой unmatched-строке, коллизии составного ключа или расхождении
   сохранить только readiness-контекст и обезличенные счетчики ошибок; витрины
   и рейтинги не строить.
7. требовать единый tenant/client scope у source-, report- и результирующих
   строк; persistence повторно проверяет в БД, что каждый cabinet/company
   принадлежит отчету и что кабинет связан именно с указанной организацией;
8. не пропускать JSON не объектного типа и не дедуплицировать строки по payload
   hash: ревизия определяется стабильным source row id, текущий refresh-run
   владеет своим source window, а неоднозначность одного слоя блокирует gate;
   revision conflict и input hash используют канонический hash фактического
   payload, а несовпадение с сохраненным raw hash отдельно блокирует расчет.
9. после создания logistics-context запрещать любую повторную запись того же
   `report_id`, включая идентичный input hash; повторный расчет выполняется
   только новым report run.
10. перед чтением file-authoritative WB Finance повторно проверить immutable
    manifest и все зарегистрированные файлы; при DB/file ambiguity или любой
    ошибке целостности сохранить только blocked readiness-контекст, не строить
    пустую logistics-витрину.

Нормализация схемы выполняется до gate. Значения WB `FBW`/`FBO` с техническим
суффиксом относятся к `fbo`, а `FBS`/`DBS` с техническим суффиксом — к `fbs`.
Русские подписи витрины `Склад WB` и `Склад продавца` нормализуются в те же
канонические значения. Только для операции `Коррекция логистики` отсутствие
`deliveryMethod` означает `scheme=not_applicable`: схема исполнения к такой
служебной корректировке неприменима. Подставлять `FBO` запрещено.

Финансовая строка с `deliveryService=0` и без `orderUid` не содержит расхода на
логистику и не может быть частью цепочки заказа. Она остается в исходной
финансовой детализации и основном отчете, но исключается из логистической
валидации, order/SKU-витрин, покрытия ключей и `order_count`. Если
`deliveryService` отличается от нуля, `orderUid` остается обязательным и его
отсутствие блокирует gate.

У строки с `deliveryService=0` и известным `orderUid` отсутствие собственной
схемы также не является ошибкой логистического факта: такая строка может только
добавить к уже существующей цепочке продажи/возвраты и выручку. Схема сегмента
берется из ненулевой логистической строки той же цепочки и даты; значение FBO
по умолчанию не создается. Если ненулевые строки самой цепочки содержат разные
FBO/FBS, gate по-прежнему блокируется. Цепочка-день без единой ненулевой
логистической строки в order/SKU-витрины не попадает.

Для граничной неполной недели основной финансовый P&L сохраняет принятую
методику закрывающей недели. Логистический блок не меняет этот P&L: он берет
точную сумму логистики из строк WB за календарные даты выбранного периода, а
недельные выручку и прибыль возвращает как недоступные. Reconciliation с
`ReportUnitRow` выполняется на полностью входящих неделях; для неполной
граничной недели контрольным фактом является тот же неизменяемый WB snapshot.
Это правило не является пропорциональным распределением недельного P&L.

# Расчетная модель

## Базовые показатели

Все денежные значения хранятся и считаются с текущей точностью расчетного слоя.
Округление для интерфейса выполняется только после агрегации.

```text
logistics_total = сумма фактической логистики по выбранному срезу

logistics_share_pct = logistics_total / revenue * 100

logistics_per_order = logistics_total / order_count

logistics_per_sale = logistics_total / sold_units

profit_without_logistics = profit_before_ndfl + logistics_total

profit_effect_amount = -logistics_total
```

Правила знаменателя:

- `revenue` берется из того же опубликованного отчета и с теми же фильтрами;
- если SKU не связан с `ReportUnitRow`, его `revenue`,
  `logistics_share_pct`, `profit_before_tax`, `profit_without_logistics` и
  `profit_effect_amount` возвращаются как `null`; точная логистика сохраняется,
  а строка получает `missing_profit_link` и `restore_profit_link`;
- финансовая связь сначала ищется по нормализованному exact-ключу
  `tenant/client/week/cabinet/company/scheme/product`; для логистической
  коррекции со `scheme=not_applicable` разрешён только односторонний alias к
  `scheme=fbo` при полном совпадении остальных измерений, потому что accepted
  финансовый отчёт исторически относит отсутствующий `deliveryMethod` к FBO;
  FBS и любой частичный/неоднозначный match не являются fallback;
- если хотя бы один SKU выбранного среза имеет `missing_profit_link`, весь срез
  получает `financialMetricStatus=not_available_missing_profit_link` и
  `sliceStatus=partial`: финансовые KPI, финансовая динамика и рейтинги по доле
  и влиянию на прибыль недоступны, но фактическая логистика, компоненты,
  количества и рейтинг по логистике остаются видимыми;
- финансовая выручка v5 хранится отдельно как nullable `financial_revenue`;
  legacy `revenue` не используется в KPI v5 и не является fallback;
- при `revenue <= 0` доля не рассчитывается и возвращается как `null` со
  статусом `not_applicable`;
- при нулевом числе заказов или продаж соответствующий показатель возвращается
  как `null`, а не как ноль;
- отрицательные корректировки сохраняют знак и не превращаются в абсолютные
  значения;
- период фильтрует логистические операции по точной календарной дате;
- если выбранный период отсекает часть недели, `revenue`, доля логистики,
  прибыль и другие недельные финансовые KPI возвращаются `null` со статусом
  `financialMetricStatus=not_available_partial_week`; пропорциональное
  распределение запрещено; SKU-грань получает
  `data_quality_status=partial_week`, а не `missing_profit_link`, и не получает
  рекомендацию `restore_profit_link`;
- presentation mode `closed_weeks` выделяет из запрошенного периода только
  полностью входящие недели понедельник–воскресенье:
  `analysisPeriodStart` равен первому понедельнику не раньше начала запроса,
  `analysisPeriodEnd` — последнему воскресенью не позже конца запроса;
- KPI, рейтинги, товары, факторы и AI-вывод в `closed_weeks` относятся только к
  `analysisPeriod`. Нельзя делить логистику неполной границы на выручку
  закрытого периода или включать такую границу в `profit_effect_amount`;
- непустые ведущая и хвостовая границы возвращаются как `partialPeriods`.
  Для них разрешены только фактическая логистика, компоненты, заказы, продажи и
  возвраты; `revenue`, доля, прибыль и влияние всегда `null`;
- если внутри запроса нет полной недели, `analysisPeriod` равен `null`,
  финансовые KPI не строятся, а доступные факты остаются в `partialPeriods`;
- режим `exact` сохраняет прежнюю семантику точного пользовательского периода и
  `not_available_partial_week`; web-сценарий и AI по умолчанию используют
  `closed_weeks`, а совместимые прямые API-вызовы без параметра остаются
  `exact`;
- `profit_before_ndfl` и состав его расходов не пересчитываются отдельной
  формулой этого блока, а переиспользуют accepted Excel-методику.

`profit_effect_amount` является знаковым полем API: отрицательное значение
означает уменьшение прибыли, положительное — увеличение прибыли из-за чистой
компенсации или корректировки. Интерфейс не показывает клиенту отрицательную
сумму без пояснения:

- при отрицательном значении: `Логистика уменьшила прибыль на X ₽`;
- при положительном значении: `Корректировки логистики увеличили прибыль на X ₽`;
- в обоих случаях `X` показывается как положительная абсолютная сумма.

Рядом отображается фактическая `profit_before_ndfl`, уже содержащая расход на
логистику.

## Разделение прямой и обратной логистики

Сумма фактической логистики берется из того же нормализованного поля, которое
использует текущий отчет. Дополнительные поля WB не могут включаться второй раз.

Каждая финансовая строка получает одно значение:

- `forward`;
- `reverse`;
- `adjustment`;
- `unclassified`.

Классификатор `wb-logistics-classifier-v1` использует консервативные правила
строки без вывода направления по соседним строкам цепочки:

- ненулевой `deliveryAmount` при нулевом `returnAmount` -> `forward`;
- ненулевой `returnAmount` при нулевом `deliveryAmount` -> `reverse`;
- оба признака равны нулю, но есть ненулевой `rebillLogisticCost` или
  подтвержденный marker перерасчета/корректировки/возмещения -> `adjustment`;
- отсутствующий признак, одновременно ненулевые признаки и любая иная
  комбинация -> `unclassified`.

Согласованы четыре взаимоисключающие категории: `forward`, `reverse`,
`adjustment` и `unclassified`. Нераспознанная операция всегда остается в
`unclassified`, включается в общий расход и не переносится в прямую или
обратную логистику по предположению. Версия классификатора входит в canonical
input hash; изменение правил требует новой версии классификатора и методики.
Правила проверяются на обезличенных fixtures.

Показатель прямой или обратной логистики показывается только вместе с покрытием
классификации. Нераспознанные строки входят в общий итог, но не переносятся в
одну из частей по предположению.

## Рейтинги товаров

Первая очередь содержит минимум три рейтинга:

1. максимальная общая сумма логистики;
2. максимальная доля логистики в положительной выручке;
3. максимальное снижение прибыли из-за логистики и возвратных операций.

Для каждого товара показываются сумма, выручка, доля, заказы, продажи,
возвраты, прибыль, влияние логистики и статус выборки. Малый объем наблюдений не
скрывается. Товар получает `low_sample`, если в выбранном срезе восстановлено
меньше 10 цепочек заказов. Порог первой версии равен `10`; изменить его можно
только вместе с версией методики после анализа распределения реальных выборок.

# Расчетные витрины

Предлагается добавить к опубликованному `report_id` четыре неизменяемые
витрины:

## `report_logistics_order_rows`

Гранулярность — восстановленная цепочка `заказ–товар–календарный день` внутри
отчета. Начало недели сохраняется отдельно для динамики.

Минимальные поля:

- tenant, client, cabinet и `report_id`;
- внутренний безопасный ключ цепочки;
- точная дата операции, начало недели, дата заказа и
  `previous_report_period` для возврата заказа прошлого периода; старый заказ
  без возврата получает нейтральный `order_before_report_period`;
- безопасный `product_ref`: общий внутри клиента для `nmId`, а SKU fallback
  дополнительно ограничен кабинетом, организацией и схемой;
- товар, артикул и схема продаж;
- склад и направление; при нескольких значениях внутри цепочки возвращается
  `mixed`, а не первое случайное значение;
- фактическая логистика всего;
- прямая, обратная, корректировки и нераспределенная часть;
- продажа, возврат, итоговое количество и выручка;
- число исходных строк и hash доказательной базы;
- `classification_status`, `coverage_status`, `data_quality_status`.

## `report_logistics_sku_rows`

Гранулярность — товар в недельном финансовом срезе отчета. Содержит
`product_ref`, начало и конец недели, сводные показатели, прибыль, ранги и
детерминированные флаги рекомендаций. `source_revenue` сохраняется отдельно как
факт исходной логистической строки, а nullable `financial_revenue` — только как
связь с `ReportUnitRow`. При отсутствующей связи финансовые поля остаются
`null`; legacy non-null колонки получают реальный source-факт или точное
`-logistics_total`, но никогда sentinel `0`. Неполная граничная неделя хранится
как `partial_week` без ложного `restore_profit_link`. Для
`scheme=not_applicable` финансовая часть может быть взята только из FBO-строки
того же exact product/week/cabinet/company scope; сама логистическая схема
остаётся `not_applicable` и не переписывается.

## `report_logistics_route_rows`

Storage-grain F-3 — неизменяемый сегмент цепочки с датой/неделей, товаром,
складом и доступным направлением доставки. Он сохраняет и явные
`missing/mixed`, чтобы фактическая логистика и denominator coverage полностью
reconciled с order mart. Read-only `/routes` SQL-агрегирует эти строки до
склада/направления после применения периода, кабинета, организации, схемы и
товара. Точная связка Statistics выполняется только по
`(wb_cabinet_id, srid, nm_id)`; глобальный coverage threshold не применяется,
потому что он скрывал бы валидный кабинет из-за частичного scope другого.

## `report_logistics_tariff_rows`

Гранулярность — кабинет, организация, схема, календарная неделя, тип тарифа
(`box`/`pallet`) и склад WB. Витрина F-2 хранит архивный тариф, запрошенный на
начало недели, либо явно маркированную `estimate` по снимку на дату сбора, если
архивная точка недоступна. Она не подменяет `report_logistics_route_rows`:
связь со складом фактической операции и направлением появляется только в F-3.

## `report_logistics_return_reason_rows`

Гранулярность F-5/R-3 — одна строка на canonical Finance return chain и товар
в tenant/client/cabinet/company/scheme scope. При нескольких Finance return
segments строка не размножается: для отображения и фильтров используется
последняя подтверждённая финансовая дата возврата.

Finance остаётся источником факта возврата. `goods-return.reason` добавляется
только после exact same-name scoped match; claims добавляет только nullable
`claim_available` и `has_user_comment`. `true/false` допустимы только внутри
подтверждённого claims coverage, а denied/unavailable и строки вне 14-дневного
окна получают `null`. Raw comments, claim IDs, media и raw `srid` в mart/API не
попадают. Integrity/scope/reconciliation failure даёт `blocked` context без
rows; missing/unmatched/empty/denied даёт `partial/data_unavailable` и само по
себе не блокирует публикацию.

Каждая витрина хранит lineage до `report_run`, версии методики, source snapshot
и hash входных данных. Старый опубликованный отчет без этих витрин не
достраивается незаметно на лету: API возвращает `needs_rebuild`.

# API

Предлагаемые защищенные read-only методы:

- `GET /api/reports/{report_id}/logistics/summary`;
- `GET /api/reports/{report_id}/logistics/products`;
- `GET /api/reports/{report_id}/logistics/orders`;
- `GET /api/reports/{report_id}/logistics/routes` — вторая очередь;
- `GET /api/reports/{report_id}/logistics/dimensions` — вторая очередь;
- `GET /api/reports/{report_id}/logistics/tariffs` — вторая очередь;
- `GET /api/reports/{report_id}/logistics/return-reasons` — F-5/R-3;
- `POST /api/reports/{report_id}/logistics/calculate` — третья очередь,
  выполняет только сценарный расчет и не меняет источники.

Методы переиспользуют авторизацию, tenant boundary, роли, пагинацию и текущие
фильтры кабинета: период, кабинет WB, схема продаж и поиск товара. Параметр
`client_company_id` (организация) остается поддержанным на уровне API как
additive-фильтр, но витрина логистики не выводит для него отдельный контрол
(см. «Интерфейс»).
`GET .../logistics/products` дополнительно принимает allowlisted
`dataQualityStatus=missing_profit_link`; иное непустое значение возвращает
HTTP 400. Фильтр применяется в SQL до подсчёта `total`, сортировки и пагинации
и не ослабляет остальные period/tenant/cabinet/company/scheme/product
ограничения.
Ответы содержат `dataStatus`, `sliceStatus`, фильтрованное `coverage`,
`reportCoverage`, включая `invalidReportRows`, `reportRequiredFieldErrors` и
`chainDimensionConflicts`, `invalidSourcePayloadShapes`,
`sourceIdentityErrors`, `sourceRevisionConflicts`, `scopeMismatches`,
`filterContext`, `financialMetricStatus`, версии
методики, классификатора и ключа, `generatedAt`, `sourceCoverageEnd`, а также
информацию о том, является значение фактом или оценкой. Фильтрованное coverage
включает `missingProfitLinks`, суммы затронутой логистики и
`lowSampleProductCount`. Пустой разрешенный срез возвращает `sliceStatus=empty`,
`financialMetricStatus=not_available_empty_slice`, nullable денежные KPI и
пустые рейтинги/рекомендации без нулевой подстановки.
Products и orders агрегируются, сортируются и пагинируются в SQL; стабильный
переход к цепочкам выполняется по `productRef`.

`GET .../logistics/summary` дополнительно принимает
`periodMode=exact|closed_weeks`. В `closed_weeks` ответ содержит:

- `periodContext` с `requestedPeriod`, nullable `analysisPeriod`, режимом и
  признаком неполных границ;
- `partialPeriods` с безопасными фактическими агрегатами без финансовых KPI;
- `insight` версии `wb-logistics-insight-v1`: `headline`, `findings`,
  `actions`, `limitations` и статусы F-1…F-5 без raw identifiers и hashes.

После summary web передает точные границы `analysisPeriod` в products и
factor API. При отсутствии полной недели эти запросы не выполняются. API не
меняет сохраненный report и не создает новый snapshot.

Одна отсутствующая граница периода дополняется границей отчета. Инвертированный
диапазон или выход за период report run возвращает HTTP 400 с кодом
`invalid_logistics_period`; молчаливое обрезание запрещено.

# Интерфейс

Сценарий не создает отдельный пункт бокового меню. Он открывается внутри
`Аналитика и таблицы` через вложенную навигацию `Сводка / Товары / Логистика /
Возвраты / Расходы WB / Исходные данные`; канонический UI-fragment —
`#tables/logistics`, а `#tables` ведет в `Сводка`. На карточке расходов WB в
`Обзоре` доступно действие `Разобрать логистику`, ведущее в тот же fragment без
сброса разрешенного draft и текущего среза.

Первый экран строится как ответ, а не как техническая витрина. Он различает
обязательный операционный расход и потенциально устранимые потери: вся сумма
логистики влияет на прибыль, но не объявляется целиком экономией, потерей или
резервом оптимизации без отдельного подтвержденного расчета.

1. Заголовок периода и короткий вывод `сколько ушло на логистику`: фактическая
   сумма логистики закрытого `analysisPeriod` и фраза о ее абсолютном влиянии
   на прибыль. Рядом видны запрошенный и фактически использованный периоды.
2. Рядом — доля в выручке и статус финансовых KPI. Для неполной недели доля и
   прибыль остаются `null`, а точная логистика не скрывается.
3. Сразу под итогом — список `зона проверки -> сумма -> основание/ограничение
   -> действие`, отсортированный по подтвержденному денежному влиянию и
   priority. Каждая строка явно помечает тип основания: `Факт`, `Ограничение`
   или `Качество данных`. Строки могут описывать пересекающиеся срезы, поэтому
   интерфейс запрещает воспринимать их как слагаемые одного итога. В первой
   строке пользователь должен увидеть главное доступное действие без раскрытия
   цепочек заказа. Действие `Проверить связь с отчётом` для
   `restore_profit_link` остаётся внутри логистического сценария, включает
   серверный фильтр `missing_profit_link`, прокручивает к рейтингу конкретных
   затронутых товаров и показывает видимый сбрасываемый статус фильтра; переход
   в общую сверку WB ↔ 1С запрещён.
4. Отдельная компактная полоса доверия показывает покрытие классификации,
   свежесть, полноту среза и `low_sample`; она не конкурирует с денежным итогом.
5. Блок `Текущая незакрытая неделя` показывает каждый `partialPeriod` только
   фактическими суммами и количеством операций, с явной фразой, что доля и
   влияние появятся после закрытия недели.
6. Единый блок `Главный вывод и что проверить` рендерит `insight`: максимум
   три факта, подтвержденные действия и ограничения F-1…F-5. `partial` не
   превращается в ноль, экономию или установленную причину.
7. Рейтинг товаров, динамика, фильтры и детерминированные рекомендации идут
   вторым уровнем после answer-first summary.
8. Детальные цепочки, dimensions, reconciliation и технические поля находятся
   в disclosure/drill-down. Цепочки доступны только `consultant/admin`;
   клиенту показываются разрешенные бизнес-поля без raw payload и внешних
   идентификаторов.
9. Блок факторов показывает возвраты, габариты, коэффициенты, склады и
   направления только при подтвержденном источнике. Finance подтверждает факт
   и сумму возврата, но не причину покупателя: при отсутствии отдельного
   источника UI пишет `Причина недоступна в Finance`, а не выводит гипотезу как
   факт.
10. Калькуляторы остаются отдельной третьей очередью с заметной меткой
    `Оценка`.

Строка фильтров витрины логистики выводит только схему продаж и поиск по
товару; период и кабинет WB берутся из верхней панели кабинета и в витрине
повторно не дублируются. Отдельный контрол `Организация` в витрине не
выводится: в текущей модели у организации ровно один кабинет WB, поэтому
разрез по организации полностью совпадает с выбором кабинета WB наверху и
дублировал бы его. Разрез по организации остается доступен через
`client_company_id` на уровне API; если у организации появится второй кабинет,
контрол возвращается отдельным additive-изменением.

Согласованный визуальный target, по которому проверяется frontend-реализация:
[`docs/design/wb-logistics-v4-analytics-target.html`](../design/wb-logistics-v4-analytics-target.html).
Он использует синтетические значения, текущие цветовые токены и компоненты и
фиксирует информационную иерархию, но не является runtime UI или источником
расчетных требований. При расхождении действуют формулы и контракты этого spec.

Обязательные состояния сценария:

| Состояние | Первый экран | Действие |
|---|---|---|
| `ready` | Фактический итог, доступные финансовые KPI, зоны проверки и trust strip. | Открыть приоритетный подтвержденный срез. |
| `partial` | Точная доступная логистика остается видимой; недоступные KPI не заменяются нулем, ограничение показано рядом. | Сначала проверить полноту и качество данных. |
| `needs_rebuild` / `blocked` | Денежный answer-first блок не строится из неполных витрин; показываются безопасный статус и причина без raw details. | Создать новый report run или устранить указанный blocker. |
| Пустой разрешенный срез | Явное `В выбранном срезе нет операций логистики`; это не подменяет ошибку загрузки и не сбрасывает фильтры. | Изменить срез. |
| Ошибка запроса | Старые цифры не выглядят актуальными; UI показывает ошибку и сохраняет выбранный контекст. | Повторить загрузку. |

На mobile ни один глобальный фильтр не скрывается CSS-правилом: выбранные
кабинет, период и схема остаются видимыми в компактной полосе с
горизонтальной прокруткой или переносом внутри компонента (организация задается
выбором кабинета WB и отдельным контролом не выводится). Карточки зон
проверки переходят в подписанный вертикальный layout, чтобы после скрытия
desktop-заголовка было по-прежнему понятно, где сумма, основание и действие.

Диагностические показатели первого экрана: логистика на заказ, возвратная
часть и количество возвратов. Обязательные защитные показатели: покрытие
классификации, свежесть данных и `low_sample`.

Фильтры синхронизируются с текущим отчетом. Переход между сводом, товаром и
заказами не должен менять выбранный срез.

# Правила рекомендаций

Рекомендация формируется из рассчитанного флага и содержит доказательство:

- высокая доля возвратной логистики -> проверить причины возвратов по доступным
  данным и карточку товара;
- подтвержденное расхождение габаритов -> проверить упаковку и данные карточки;
- высокий расход на конкретном направлении -> проверить распределение запасов;
- высокая логистика при положительных продажах -> проверить цену, упаковку и
  маржинальность;
- недостаточное покрытие -> сначала восстановить данные, а не делать вывод.

Публичная строка рекомендации содержит `code`, `priority`, `title`, `message`,
nullable `impactAmount`, `evidenceType` (`fact`, `limitation` или
`data_quality`), nullable `actionTarget` (`products` или `source`),
`actionLabel` и безопасный агрегат `evidence`. Сортировка выполняется по
priority, затем по убыванию абсолютного `impactAmount`; отсутствие суммы идет
после подтвержденных сумм. Причина возврата без отдельного источника всегда
маркируется ограничением и текстом `Причина недоступна в Finance`.

Лидеры обратной логистики и доли в выручке выбираются отдельными SQL-запросами
по полному фильтрованному срезу. Использовать top-10 общей логистики или
глобальное coverage для рекомендаций выбранного среза запрещено.

Фразы о качестве фото, размерной сетке, цене или несоответствии ожиданиям могут
быть только гипотезами для ручной проверки. Они не отображаются как установленная
причина возврата.

# AI Boundary

AI получает только рассчитанные витрины и разрешенные evidence-поля. Он может:

- пересказать основные отклонения простым языком;
- объяснить, почему товар попал в рейтинг;
- разделить факт, оценку и гипотезу;
- предложить приоритет ручной проверки.

Для staff AI читает период из сохраненного thread scope. Если scope содержит
границы экрана логистики, base digest и F-1…F-5 строятся по тому же
`analysisPeriod`; при отсутствии границ используется `closed_weeks` полного
report run. `draft_management_report` и детерминированный клиентский
аналитический документ используют тот же `insight`, а не отдельный LLM-расчет.
Факторный digest ограничен статусом, coverage, подтвержденными рекомендациями и
безопасными агрегатами; raw rows, external IDs, hashes и комментарии в AI не
передаются.

AI не может:

- читать raw payload клиента напрямую;
- изменять WB, 1С или расчетные витрины;
- подставлять отсутствующее значение как ноль;
- придумывать причину возврата;
- объявлять товар убыточным только по одной строке или одному коэффициенту.

# Калькуляторы

## Логистика

Входы: период тарифа, схема, склад или тарифная зона, габариты с упаковкой,
вес, коэффициент и сценарная вероятность обратной операции. Набор входов
уточняется после проверки доступных официальных тарифов.

Выходы: оценка прямой, обратной и общей логистики, диапазон при неполных данных,
доля в цене/выручке и список использованных предположений.

## Маржинальный доход на единицу

Калькулятор переиспользует детерминированный waterfall accepted Excel-методики:
выручка, себестоимость, комиссия, хранение, логистика, приемка, продвижение,
штрафы, эквайринг и применимые налоги. Он показывает фактические значения
выбранного товара рядом со сценарием пользователя.

Сценарий не сохраняется как новая финансовая операция и не меняет отчет.

# Ошибки и пограничные случаи

- Возврат текущего периода может относиться к заказу прошлого периода. Такая
  строка входит в финансовый факт периода, но связь с заказом получает отдельный
  статус.
- Несколько строк одного заказа не должны увеличивать `order_count`.
- `srid` не участвует в ключе и не используется как молчаливый fallback.
- Корректировка после публикации требует нового `report_run`, а не изменения
  старой витрины.
- Новый обязательный контекст со статусом `blocked`, отсутствующий контекст или
  устаревшая методика создают неотменяемый publication blocker.
- Несовместимая `chain_key_version` возвращает `needs_rebuild` и создает
  отдельный неотменяемый blocker `logistics_analysis_key_outdated`.
- Report-строка без обязательной даты сохраняет сумму в контрольном итоге, но
  блокирует построение order/SKU-витрин.
- Разные организации или схемы внутри одной цепочки и календарного дня не
  разделяются на сегменты, а блокируют gate.
- `partial` остается review-статусом; старый отчет без
  `logistics_analysis_required` не блокируется, но API возвращает
  `needs_rebuild`.
- При отсутствии направления доставки route mart сохраняет недоступную строку
  цепочки, чтобы coverage и reconciliation оставались полными.
- При отсутствии исторического тарифа калькулятор показывает оценку по явно
  выбранному тарифу, но не объясняет им исторический факт.
- Нулевая или отрицательная выручка не приводит к бесконечной доле.
- Валюта первой версии — рубли; правила иной валюты не определены.

# Безопасность и tenant isolation

- Каждый запрос ограничен tenant/client/cabinet доступами текущего пользователя.
- Внешние интеграции остаются read-only.
- Raw payload, токены и секреты не возвращаются интерфейсу и AI.
- Безопасный ключ цепочки заказа не должен раскрывать внешний идентификатор
  клиенту, если он не нужен для бизнес-сценария.
- Действующие audit, session, retention и backup правила web-кабинета
  применяются без ослабления.

# Этапы реализации

## Этап 0. Техническая проверка источников

- добавить безопасный агрегатный профилировщик — выполнено;
- проверить текущий локальный снимок — выполнено, обнаружены коллизии кандидатов
  на ключ;
- расширить запрос и raw-слой дополнительными официальными полями — выполнено
  в коде, требуется новый снимок;
- зафиксировать версионированную таблицу классификации реальных операций;
- подтвердить order-level ключ на новом снимке без коллизий;
- подготовить доказательную выборку для начала разработки.

## Рабочие пакеты реализации

1. `WP-0 Источники и raw-контракт`: профилировщик, дополнительные поля запроса,
   nullable-колонки raw-слоя и повторный снимок.
2. `WP-1 Ключ и классификатор`: составной безопасный ключ при необходимости,
   четыре согласованные категории, версия правил и collision guard.
3. `WP-2 Витрины`: daily order-level и weekly SKU-level таблицы, lineage,
   полные input hashes, статусы качества и многомерная сверка — реализовано за
   выключенным флагом.
4. `WP-3 API и кабинет`: summary, products, orders, точные фильтры, SQL-
   пагинация, роли, рекомендации и клиентские формулировки — реализовано за
   выключенным флагом.
5. `WP-4 Приемка и rollout`: повторяемость, tenant tests, staff-only проверка,
   затем отдельное включение клиентским ролям.
6. `WP-5 Факторы`: F-1…F-5 приняты на staff-only test; для F-5 R-1…R-4
   реализованы и влиты, R-5 test acceptance завершён. Клиентское и production-
   включение остаются отдельными решениями.

`WP-4` начат после исторического прохождения gate v4 на read-only test-снимке.
Вложенная information architecture и frontend-реализация v5 приняты на test.
Следующий шаг определяется отдельным решением о клиентском или production
rollout; калькуляторы остаются третьей очередью.

## Этап 1. Фактический MVP

- расширить нормализацию нужными order-level полями;
- добавить расчетные витрины заказов и товаров;
- реализовать summary, products и orders API;
- добавить первый экран кабинета и рекомендации;
- выполнить полную сверку с текущим отчетом.

Оценка после утверждения источников: 5–7 рабочих дней.

## Этап 2. Факторы

- подключить read-only габариты, замеры и штрафы;
- добавить коэффициенты, склады и доступные направления;
- реализовать tariff/route/dimensions витрины и интерфейс;
- проверить покрытие и ложные выводы.

Оценка: 5–7 рабочих дней.

## Этап 3. Калькуляторы и расширенный AI

- реализовать оба сценарных калькулятора;
- показать сравнение факта и сценария;
- расширить AI-пояснения в рамках разрешенных данных;
- провести staff-only приемку и rollout.

Оценка: 4–6 рабочих дней.

Суммарная предварительная оценка — 3–4 недели. Она уточняется после этапа 0.

# Acceptance Criteria

Документ принят как цель реализации. Техническая проверка источников на этапе 0
не может молча менять согласованные формулы, четыре категории классификации,
порог `low_sample`, состав MVP или границу факт/оценка. Если источник делает
требование невыполнимым, изменение возвращается на отдельное согласование.

Первая очередь считается готовой, когда:

1. итоговая логистика по одинаковому срезу сверяется с текущим опубликованным
   отчетом глобально и по неделе, кабинету, организации, схеме и товару с
   расхождением не более `0,01 ₽`;
2. заказ с несколькими финансовыми строками учитывается в `order_count` один
   раз;
3. общий итог не уменьшается из-за нераспознанной прямой/обратной части;
4. каждая карточка товара трассируется до расчетной витрины и source hashes;
5. факт, оценка, гипотеза и отсутствие данных визуально различимы;
6. фильтры дают согласованные KPI, рейтинги и детализацию;
7. пользователь одного tenant не может получить данные другого;
8. старый отчет без новых витрин возвращает `needs_rebuild`;
9. AI не получает raw payload и не придумывает причины возврата;
10. ни один сценарий не выполняет запись во внешнюю систему.
11. missing/invalid обязательные поля создают `blocked` и сохраняют только
    readiness-контекст без order/SKU-витрин.
12. неполная неделя возвращает точную логистику и `null` для недельных
    финансовых KPI.
13. повторный импорт того же `report_id` после создания logistics-context
    запрещен; исправление выполняется новым report run.
14. строки `ReportUnitRow` без обязательных dimensions входят в контрольную
    сумму, получают счетчики качества и блокируют витрины.
15. контексты v1–v5 и несовместимая версия ключа возвращают `needs_rebuild`.
16. поврежденный JSON payload, смешанный tenant/client scope, неоднозначная
    ревизия или неизвестный context status не могут дать `ready` или публикацию.
17. все logistics endpoint отклоняют инвертированный и внешний период кодом
    `invalid_logistics_period`.
18. `Коррекция логистики` без `deliveryMethod` получает
    `scheme=not_applicable`, не создает ложный конфликт с FBO/FBS той же цепочки
    и не увеличивает `order_count` отдельным заказом.
19. строка с `deliveryService=0` и без `orderUid` остается в финансовом отчете,
    но не блокирует logistics gate и не входит в логистические цепочки; та же
    строка с ненулевой логистикой блокирует gate.
20. на неполных граничных неделях точная календарная логистика сверяется с WB
    snapshot, финансовые KPI не восстанавливаются из полной недели, а полные
    недели продолжают сверяться с `ReportUnitRow` по всем dimensions.
21. боковое меню не содержит отдельный пункт `Логистика`; сценарий доступен в
    фиксированной вложенной навигации `Аналитика и таблицы`.
22. `#tables/logistics`, browser Back/Forward и действие
    `Разобрать логистику` открывают один сценарий и сохраняют разрешенный
    `report_id`, кабинет, организацию, схему и период.
23. первый viewport без раскрытия details отвечает на вопросы `сколько`,
    `на каком основании/с каким ограничением` и `что делать`: показывает
    денежный итог, абсолютное влияние, финансовый статус и минимум одну
    приоритетную строку `зона проверки -> сумма -> основание/ограничение ->
    действие`.
24. детальные цепочки и технические поля не находятся на первом уровне и не
    содержат raw payload или внешние идентификаторы.
25. Finance-return без отдельного подтвержденного источника показывает
    `Причина недоступна в Finance`; факт, ограничение и гипотеза визуально не
    смешиваются.
26. при выключенном `SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED` client role не
    видит сценарий и overview-action, не может загрузить logistics API прямым
    fragment и не получает косвенный статус существования draft.
27. desktop, tablet и ширина 390 px не имеют page-level horizontal overflow;
    вложенная навигация остается клавиатурно доступной, активный сценарий имеет
    `aria-current`, а после перехода focus попадает на заголовок сценария.
28. frontend соответствует согласованной структуре visual target; различия в
    иерархии или составе первого viewport требуют обновления и повторной
    приемки spec/target до rollout.
29. общая сумма логистики не называется целиком устранимой потерей, резервом
    экономии или потенциальной выгодой; такие значения требуют отдельной
    формулы и evidence.
30. пересекающиеся зоны проверки визуально не представляются как слагаемые;
    для каждой строки виден тип `Факт`, `Ограничение` или `Качество данных`.
31. `ready`, `partial`, `needs_rebuild`/`blocked`, пустой срез и ошибка запроса
    имеют разные состояния без нулевой подстановки и без показа устаревших цифр
    как актуальных.
32. на ширине 390 px остаются доступны все значения глобального среза, а каждая
    свернутая в карточку строка сохраняет видимые подписи суммы, основания и
    действия.
33. SKU без связи с `ReportUnitRow` сохраняет фактическую логистику, но
    возвращает `null` для всех финансовых полей, статус `missing_profit_link` и
    рекомендацию `restore_profit_link`; наличие такой строки переводит
    финансовые KPI всего выбранного среза в fail-closed состояние без частичного
    `SUM` или fallback на Finance-выручку.
34. tenant, client, cabinet, company и product dimensions нормализуются единым
    `strip`, а схема дополнительно `casefold`; различия только в пробелах не
    разрывают связь с `ReportUnitRow`.
35. verified file-authoritative WB Finance строит те же logistics context,
    order/SKU marts и input hash, что и DB-authoritative snapshot; отсутствие
    `SourceSnapshotRow` при `skipped_large_snapshot` не превращается в пустой
    источник, а ambiguity или нарушение raw integrity блокирует gate.
36. F-5 сохраняет ровно одну строку на canonical Finance return chain; несколько
    return segments используют последнюю подтверждённую Finance return date и
    не создают fanout.
37. empty/denied/unmatched/out-of-window claims остаются nullable
    `data_unavailable` и не блокируют основную логистику или публикацию; только
    exact scoped match создаёт безопасные `claimAvailable`/`hasUserComment`.
38. context+rows причин сохраняются атомарно только в draft; published run
    immutable, а integrity/scope/row-count mismatch fail closed.
39. `/logistics/return-reasons` соблюдает tenant/role/flag matrix, считает
    coverage по полному SQL-срезу и не возвращает raw `srid`, source hashes,
    claim IDs, комментарии или media.
40. SKU на неполной граничной неделе сохраняет точную логистику и nullable
    финансовые поля со статусом `partial_week`; он не увеличивает
    `missingProfitLinks` и не получает `restore_profit_link`.
41. `scheme=not_applicable` связывается с финансовой строкой FBO только при
    exact совпадении tenant/client/week/cabinet/company/product. FBS, соседняя
    неделя, другой товар или другой scope не используются как fallback; при
    отсутствии FBO связь остаётся fail-closed.
42. Действие `Проверить связь с отчётом` запрашивает и показывает только товары
    с `missing_profit_link`, сохраняет текущий разрешённый срез, имеет видимый
    сброс фильтра и не открывает общую сверку WB ↔ 1С.
43. `closed_weeks` выделяет все полные недели внутри выбранного периода,
    считает финансовые KPI только по ним и возвращает неполные границы
    отдельно без cross-period знаменателя.
44. Если полной недели нет, UI показывает фактический partial-блок и объяснение
    вместо пустого или нулевого финансового итога.
45. Products и F-1…F-5 на странице относятся к тому же `analysisPeriod`, что и
    основные KPI; stale response предыдущего report/build не рендерится.
46. `insight` детерминирован, одинаков по смыслу в web, AI management report и
    аналитическом Markdown/DOCX и не называет `partial` экономией.
47. AI использует period scope текущего экрана и не получает raw identifiers,
    hashes, claims comments или отсутствующие финансовые значения как нули.
48. Пакет не меняет report rows, schema, source lineage, feature flags или
    client/production rollout.

# Test Plan

## Unit

- классификация продажи, доставки, возврата, отмены и корректировки;
- цепочка из нескольких строк;
- возврат заказа прошлого периода;
- неизвестная операция;
- нулевая и отрицательная выручка;
- отрицательная корректировка;
- `Коррекция логистики` без схемы и рядом с FBO/FBS-строкой той же цепочки;
- нулевая логистика без `orderUid` и ненулевая логистика без `orderUid`;
- нулевая логистика с `orderUid`, но без собственной схемы, рядом с ненулевой
  строкой цепочки и без нее;
- варианты схем WB `FBW, (...)`, `FBS, (...)` и русские подписи витрины;
- точные суммы на обеих неполных граничных неделях без подстановки недельных
  финансовых KPI;
- SKU без profit link: nullable financial fields, сохраненная логистика,
  `missing_profit_link`, отсутствие `check_margin` и запрет source-revenue
  fallback;
- неполная граничная неделя: `partial_week`, nullable financial fields и
  отсутствие `restore_profit_link`;
- односторонний alias `not_applicable → fbo` только при exact совпадении
  остальных измерений; FBS и частичные совпадения не принимаются;
- одинаковая связь order/SKU/report при пробелах вокруг любой строковой
  dimension;
- exact goods-return/claims scoped links, nullable claims coverage и схлопывание
  нескольких return segments до последней Finance return date;
- расчет каждого KPI без раннего округления.
- выделение накопленного закрытого периода и обеих неполных границ;
- отсутствие полной недели и запрет cross-period финансовых KPI;
- детерминированный insight для ready/partial/missing-link состояний.

## Contract And Repository

- additive raw/normalized schema;
- сохранение lineage и hash;
- изменение организации, dimensions, статуса качества, source row/hash или
  отображаемых metadata меняет input hash;
- изменение эффективных границ отчета меняет input hash и статус исторического
  заказа;
- tenant и role boundaries;
- mixed tenant/client и persistence результата из чужого scope;
- non-object payload, overlap base/current и конфликт ревизий одного слоя;
- parity DB-authoritative/file-authoritative snapshot, page-wise чтение,
  DB/file ambiguity, unsafe path и повторная проверка raw integrity;
- фильтры, сортировка и пагинация;
- `needs_rebuild`, `partial`, `missing`, `low_sample`;
- atomic return-reason context+rows, published immutability и required-context
  readiness для `ready`/`partial`/`blocked`;
- отсутствие raw payload в клиентском ответе.

## Reconciliation

- сумма order-level витрины равна сумме SKU-level витрины;
- сумма SKU-level логистики равна действующему отчету;
- одинаковые глобальные суммы при переставленных товарах, кабинетах,
  организациях, схемах или неделях блокируются;
- source/order/SKU/report повторно сверяются по dimensions после агрегации;
- конфликт организации или схемы внутри цепочки блокирует gate;
- повторная сборка из одинаковых snapshots дает тот же результат и hash;
- компоненты не приводят к двойному включению расхода.
- return-reason row count совпадает с числом canonical Finance return chains
  при отсутствии blocking integrity failures.

## Web And AI

- smoke-тест всех экранов и переходов;
- согласованность фильтров;
- рекомендации по полному срезу, включая лидера вне top-10 общей логистики;
- HTTP 400 для инвертированного и внешнего периода;
- мобильная ширина, клавиатурная навигация и читаемые статусы;
- nested navigation, `#tables/logistics`, Back/Forward, focus transfer,
  `aria-current` и сохранение разрешенного draft/фильтров;
- отсутствие отдельного sidebar-пункта, overview-action и logistics API-вызова
  для client role при выключенном client flag;
- visual regression first viewport на desktop и 390 px относительно
  согласованного target: summary, список проблем, trust strip и свернутый
  второй уровень;
- state matrix для `ready`, `partial`, `needs_rebuild`/`blocked`, пустого среза
  и ошибки запроса без stale/zero fallback;
- mixed ready/missing-profit-link срез: fail-closed summary/dynamics,
  отсутствующие финансовые рейтинги и доступная точная логистика;
- allowlisted products-фильтр `dataQualityStatus=missing_profit_link`,
  SQL-пагинация/`total`, отказ на неизвестном значении и UI-action с видимым
  сбросом без перехода в общую сверку;
- семантический regression: итоговая логистика не называется целиком
  устранимой потерей, а пересекающиеся зоны проверки нельзя ошибочно сложить;
- mobile regression: глобальные фильтры не скрываются, карточки зон проверки
  сохраняют подписи полей;
- AI отвечает только по рассчитанным данным;
- summary `periodContext` и `partialPeriods`, последовательная загрузка
  products/F-1…F-5 по `analysisPeriod`, сброс stale состояния при смене report;
- одинаковый logistics insight на странице, в AI management report и
  Markdown/DOCX; AI thread scope задаёт фактический период;
- return-reasons API: SQL filters/sorting/pagination, full-slice coverage,
  role/flag 404 и отсутствие raw/hash/PII;
- калькулятор явно помечает сценарный результат как оценку.

# Rollout And Rollback

1. Собрать витрины для одного репрезентативного отчета в staff-only test.
2. Сверить агрегаты и вручную проверить несколько обезличенных цепочек.
3. Включить раздел consultant/admin без клиентской публикации.
4. После приемки включить клиентским ролям.
5. Калькуляторы выпускать отдельным feature flag после фактического блока.

DB-authoritative и verified file-authoritative refresh являются поддержанными
входами одного gate. Feature flag web-интерфейса и flag scheduled
source-refresh worker по-прежнему разделяются: worker включается только после
отдельного test-rollout с реальным large snapshot, подтвержденной storage
parity и resource gate. При нарушении file integrity или ambiguity новый run
обязан получить `blocked`, а не пустые витрины.

Staff-only приемка draft выполняется по прямой ссылке кабинета с
`report_id=<draft_report_id>`. Frontend может выбрать эту ревизию только из
списка отчетов, уже отфильтрованного сервером для текущего пользователя;
произвольный или клиентский draft не открывается и не обходит role/tenant gate.

Rollback отключает новый раздел и новые API-маршруты, не изменяя существующие
отчеты. Отключение флага не снимает publication blocker с report run, который
обязан был пройти gate, но не прошел его. Новые витрины являются добавочными и
остаются неизменяемыми; v1–v5-строки не переписываются. Внешние источники при
rollout и rollback не изменяются.

# Согласованные решения

1. Фактическая логистика делится на `forward`, `reverse`, `adjustment` и
   `unclassified`; нераспределенная часть входит в общий итог без выдуманной
   причины.
2. `low_sample` ставится при количестве восстановленных цепочек заказов меньше
   10; товар остается в рейтинге.
3. Влияние показывается фразой `Логистика уменьшила прибыль на X ₽` с
   положительной абсолютной суммой и фактической прибылью рядом.
4. Исторический расход объясняется только историческими данными. Текущие
   габариты и тарифы используются только как сценарная `Оценка`.
5. Excel-экспорт выпускается после приемки web-MVP.
6. MVP включает сводные KPI, динамику, рейтинги, подтвержденное разделение
   прямой и обратной логистики, влияние на прибыль, детализацию цепочки заказа,
   рекомендации и статусы качества данных. Габариты, маршруты и калькуляторы
   выпускаются следующими очередями.
7. Для `Коррекция логистики` без `deliveryMethod` используется
   `scheme=not_applicable`; это служебная корректировка, поэтому FBO не
   подставляется и отдельный заказ не считается.
8. Финансовая строка с нулевой логистикой и без `orderUid` не участвует в
   логистических цепочках и не блокирует gate. При ненулевой логистике
   `orderUid` обязателен.

# Changelog

- 2026-07-25 — принят presentation-layer контракт
  `wb-logistics-insight-v1`: накопленные KPI считаются только по полным неделям
  выбранного периода, неполные границы возвращаются отдельными фактами, а
  единый детерминированный вывод используется web, staff AI и аналитическим
  документом. Source refresh, DB migration, Excel, client/production rollout и
  калькуляторы не входят.

- 2026-07-25 — после отдельной финансовой приемки пользователя готовый
  `wb-logistics-v6` draft атомарно опубликован как current только на test.
  Перед операцией создана и верифицирована внешняя резервная копия PostgreSQL.
  Post-publish DB/API/browser acceptance подтвердил готовый Excel, `ready`
  базовую логистику, явные `partial` F-1…F-5, пустой фильтр
  `missing_profit_link` и отсутствие browser/network errors. Test остается
  staff-only; client login/client flags и production report/flags не менялись.
  Реальные identifiers, hashes, суммы и клиентские строки не фиксировались.

- 2026-07-25 — методика повышена до `wb-logistics-v6`: неполные граничные
  недели отделены от настоящего `missing_profit_link`, а финансовая связь
  нейтральной логистической коррекции получила детерминированный односторонний
  alias `not_applicable → fbo` при exact совпадении остальных измерений.
  Products API и действие рекомендации получили allowlisted фильтр только
  затронутых строк. Свежая environment-проверка также зафиксировала фактический
  staff-only rollback test после исторического R-6; production остаётся без
  logistics rollout. Идентификаторы отчётов, source hashes, объёмы и реальные
  строки в документ не переносились.

- 2026-07-23 — завершён отдельный R-6 client-role rollout только на test.
  Immutable runtime собран из `b4d7376` с `sourceDirty=false`; tracked
  `zzz-logistics-r6-client-test.conf` включает client login и все
  master/client flags F-1…F-5 с корректным приоритетом над EnvironmentFile.
  Client API текущего published report отвечает 200 для F-1…F-5; R-5 draft,
  чужой client/tenant scope и staff order chains закрыты 404. Исправлен 500 на
  чужом `client_id`, raw/hash/PII поля отсутствуют. Browser QA 1440×900 и
  390×844 прошёл без overflow и ошибок. Временный контур очищен; production и
  публикация draft не менялись.

- 2026-07-23 — завершён F-5/R-5 staff-only test acceptance на immutable
  `main@a9ec18c` с `sourceDirty=false`. Test-only full refresh создал
  неопубликованный `needs_review` draft с `partial` return-reasons context без
  blockers; Finance chains, mart/context reconciliation, safe staff API,
  SQL-сортировка/пагинация и browser QA 1440×900/390×844 подтверждены.
  Client API возвращает 404, блок скрыт и request не выполняется; все factor
  client flags явно `false`. Временный acceptance-контур очищен. Production,
  published current report и client flags не менялись.

- 2026-07-23 — реализован F-5/R-4 без environment rollout: coverage-first
  блок причин возвратов встроен после факторов и до рейтинга товаров,
  поддерживает feature-flag/no-request boundary, все API states,
  SQL-сортировку/пагинацию, desktop-таблицу и mobile-карточки. Empty/denied
  claims показаны как неполное покрытие, а не blocker; UI не раскрывает raw
  comments, IDs, media, hashes или raw `srid` и рендерит рекомендации только по
  `evidenceType=fact`. Synthetic browser QA 1440×900 и 390×844 прошёл без
  console/network errors и overflow; test/production/client flags и reports не
  менялись. Следующий пакет — R-5 staff-only acceptance/rollout.

- 2026-07-23 — пользователь принял fail-soft R-2: `confirmed_empty` и
  `access_denied` показываются как честные per-cabinet статусы и не блокируют
  основную логистику, публикацию или реализацию claims connector/selector.
  Exact claims→Finance join остаётся обязательным только для конкретного
  `claimAvailable=true` и активируется автоматически после появления доступа
  и совместимых keys; raw comments, IDs и media не выходят из защищённого raw
  snapshot. В текущем change set реализован R-2 source subset и безопасная
  staff source-state пометка. R-0I теперь возвращает
  `claimsImplementationGate=true` для принятого fail-soft контракта, не меняя
  диагностический `claimsIdentityGate`; report-level mart/API/client UI
  остаются R-3/R-4.

- 2026-07-22 — после merge PR №57 отдельно разрешённый repeat R-0I из
  `main@0deacf4` подтвердил claims active/archive schema, полную provider-total
  pagination и `paginationMismatchPresent=false`. Доступный scope пуст, другой
  закрыт по доступу; claims source keys и положительный identity gate не
  получены, поэтому R-2 и общий gate остаются закрыты. Test preflight остановлен
  выключенным source-refresh master, dry-run не создал report; production
  runtime, reports и flags не менялись.

- 2026-07-22 — после merge PR №56 claims R-0/R-0I runner приведён к принятому
  контракту полной active/archive pagination: `limit=200`, bounded offset,
  rate-limit pacing, неизменный provider total, duplicate-ID guard и boolean
  `paginationMismatchPresent`. Частичные keys не участвуют в identity gate;
  R-2, mart/API/UI и rollout остаются закрыты.

- 2026-07-22 — реализован F-5/R-1 source package без rollout: registered
  `wb_goods_return` collection, raw integrity, DB/file selector, strict
  envelope/window, deterministic normalization и exact Finance.srid linker.
  Claims, R-3 mart/API/UI, publication readiness и flags не менялись.

- 2026-07-22 — отдельно принят source-specific контракт F-5/R-1: exact
  `goods-return.srid → Finance.srid`, обязательные tenant/client/cabinet/nm
  dimensions и одна canonical return chain с return fact. Открыт только R-1;
  claims/complete и общий implementation gate остаются закрыты, mart/API/UI и
  rollout не разрешены.

- 2026-07-22 — после отдельно разрешённого production full source refresh
  создан новый неопубликованный immutable draft с verified file-authoritative
  Finance без DB/file ambiguity; опубликованный current report и flags не
  менялись. Повторный R-0I подтвердил exact
  `goods-return.srid → Finance.srid` и canonical return chain, но claims source
  keys в текущем окне отсутствуют. Goods-return gate открыт, claims/complete
  gates закрыты; `contractChangeRequired=true`, `implementationGate=false` до
  отдельного accepted-решения.

- 2026-07-22 — F-5 R-0L read-only проверил существующие immutable reports и
  не нашёл verified unambiguous Finance return lineage. Наличие кандидатов и
  return fact подтверждено, но на момент этого прохода source integrity failure
  и DB/file ambiguity сохранялись; `newReportRequired=true`, implementation
  gate был закрыт. Evidence не разрешало production migration/runtime rollout,
  retention mutation или изменение опубликованного report.

- 2026-07-22 — F-5 R-0I выполнен fail closed: внешний source gate пройден, но
  выбранный Finance lineage имеет DB/file storage ambiguity. Exact same-name
  crosswalk не оценён как verified; все identity gates и implementation gate
  закрыты. Следующий допустимый шаг — новый immutable report из однозначного
  verified storage, без изменения опубликованных отчётов и production/client
  enable.

- 2026-07-22 — синхронизировано фактическое состояние F-1…F-4 после
  staff-only test acceptance; принят подчинённый F-5 контракт причин возвратов.
  `goods-return.reason` остаётся отдельным source fact, claims передаёт только
  безопасные признаки, join точный cabinet/srid/nm, а до end-to-end кода
  разрешён только boolean-only R-0 probe. Production/client enable не выполнен.

- 2026-07-21 — F-3 уточнён до атомарной route evidence: exact
  cabinet/srid/nm join, explicit missing/mixed, полная reconciliation с order
  mart и SQL-агрегация `/logistics/routes` после фильтров. Точный контракт,
  flags и rollout находятся в accepted factor-spec.

- 2026-07-21 — F-2 тарифы выделены в отдельные immutable tariff context/mart и
  read-only `/logistics/tariffs`: это позволяет показать архивный факт или
  явно маркированную текущую оценку до появления склада/направления F-3, не
  подменяя `report_logistics_route_rows` и не меняя финансовый итог.

- 2026-07-18 — large WB Finance snapshot закреплен как поддержанный
  file-authoritative вход logistics gate: reader повторно проверяет raw
  integrity, читает страницы в границах зарегистрированного каталога и
  сохраняет storage-neutral source identity/hash; DB/file ambiguity fail
  closed вместо пустой витрины.
- 2026-07-18 — формализован `wb-logistics-classifier-v1` без chain inference и
  включен в input hash; API дополнен временем построения, концом покрытия,
  `lowSampleProductCount` и структурированными рекомендациями. Frontend
  перестроен в answer-first порядок, добавлены явные empty/error states и
  подписанный mobile-layout зон проверки; rollout и ручная browser-приемка не
  выполнялись.
- 2026-07-18 — методика повышена до `wb-logistics-v5`: удален fallback
  `source_revenue` при отсутствии связи с `ReportUnitRow`, введены nullable
  `financial_revenue`, fail-closed финансовые KPI среза и единая нормализация
  dimensions; v1–v4 требуют нового immutable report run. Operational state
  отделен от code defaults, а историческая матрица этапа 0 явно помечена.
- 2026-07-18 — закреплена граница с source-refresh `files_only`: текущий v4
  требует проверяемых `source_snapshot_rows`, разовый staff-rebuild использует
  идемпотентное восстановление уже сохраненного immutable snapshot и новый
  report run, а scheduled worker flag не включается до file-authoritative
  reader или отдельного решения о `legacy`.
- 2026-07-17 — согласована information architecture без отдельного пункта
  `Логистика`: сценарий перенесен в `Аналитика и таблицы`, закреплены
  `#tables/logistics`, answer-first summary, граница между расходом и устранимой
  потерей, типы основания зон проверки, безопасное отображение отсутствующей
  причины возврата, state matrix, desktop/mobile acceptance criteria и
  синтетический visual target до frontend-реализации; методика
  `wb-logistics-v4` не изменена.
- 2026-07-17 — согласованы правила реального WB-снимка: варианты FBW/FBS
  нормализуются, `Коррекция логистики` без схемы получает `not_applicable`, а
  нулевые финансовые строки без `orderUid` не участвуют в логистическом gate;
  также уточнена граница с методикой закрывающей недели основного P&L и
  безопасная staff-ссылка на конкретную draft-ревизию.
- 2026-07-17 — повторный bug-аудит устранил частичную агрегацию товара при
  смене названия внутри одного `productRef` и закрепил стабильный порядок
  рекомендаций по `priority` и коду.
- 2026-07-16 — закрыт дополнительный hardening-аудит v4: persistence теперь
  проверяет владельцев cabinet/company и их связь, revision gate пересчитывает
  canonical payload hash и блокирует поврежденный сохраненный hash, а повторная
  запись logistics-context запрещена даже при идентичном input hash.
- 2026-07-16 — методика повышена до `wb-logistics-v4`: добавлены строгая
  tenant/client изоляция расчета и persistence, детерминированный владелец
  ревизии source row, блокировка non-object payload и неизвестного context
  status, точные parsers даты/схемы/Decimal, SQL-рекомендации полного среза,
  HTTP 400 для некорректного периода и additive schema migration v4; v1–v3
  требуют нового report run, feature flags остаются выключенными.
- 2026-07-16 — методика повышена до `wb-logistics-v3`: устранены ложные `ready`
  при конфликте схем/организаций и отсутствии даты `ReportUnitRow`, добавлены
  post-build dimension reconciliation, period-aware input hash, единая проверка
  версии методики/ключа и additive schema migration v3; v1/v2 требуют нового
  report run, feature flags остаются выключенными.
- 2026-07-16 — принят и реализован hardening `wb-logistics-v2`: строгая
  валидация без silent defaults, многомерный reconciliation, полный canonical
  input hash, daily order grain, безопасный `product_ref`, точные календарные
  фильтры, `null` KPI для части недели, SQL aggregation/pagination, обязательный
  readiness blocker и отдельная schema migration; флаги остаются выключенными
  до нового test-снимка.
- 2026-07-16 — реализован staff-ready код первой очереди: детерминированный
  расчет, immutable order/SKU marts, gate и reconciliation, read-only API,
  staff-only web-раздел, безопасный AI digest и два выключенных feature flag;
  новый test-снимок и ручная приемка еще не выполнены.
- 2026-07-16 — начат этап 0: добавлен безопасный профилировщик, зафиксирована
  матрица готовности, обнаружен запрет на одиночный ключ `orderUid`/`srid`,
  расширены поля финансового raw-контракта и определен gate нового снимка.
- 2026-07-16 — статус изменен на `accepted`: согласованы все шесть бизнес-
  решений, порог `low_sample = 10`, клиентская семантика влияния на прибыль,
  граница исторического факта и оценки, web-first порядок и состав MVP.
- 2026-07-16 — создан draft по запросу клиента: фактическая логистика, товары с
  максимальными затратами, факторный анализ, детализация заказов, рекомендации
  и последующие калькуляторы.
