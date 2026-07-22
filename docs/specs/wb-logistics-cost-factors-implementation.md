---
spec_id: "workspace-shumeyko-partners-wb-logistics-cost-factors-implementation"
title: "WB: факторы затрат на логистику (вторая очередь)"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "consultant"]
source_of_truth: false
related_code: [scripts/probe_wb_logistics_factors.py, src/wb_unit_economics/wb_content.py, src/wb_unit_economics/wb_measurements.py, src/wb_unit_economics/wb_tariffs.py, src/wb_unit_economics/wb_goods_return.py, src/wb_unit_economics/wb_supplier_sales.py, src/wb_unit_economics/wb_stocks.py, src/wb_unit_economics/logistics_analysis.py, src/wb_unit_economics/web/source_refresh.py, src/wb_unit_economics/web/repository.py, src/wb_unit_economics/web/models.py, src/wb_unit_economics/web/database.py, src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/settings.py, src/wb_unit_economics/web/static/index.html, src/wb_unit_economics/web/static/app.js, src/wb_unit_economics/web/static/styles.css, sql/postgres_schema.sql]
related_tests: [tests/test_probe_wb_logistics_factors.py, tests/test_wb_content.py, tests/test_wb_measurements.py, tests/test_wb_tariffs.py, tests/test_wb_goods_return.py, tests/test_wb_supplier_sales.py, tests/test_wb_stocks.py, tests/test_logistics_analysis.py, tests/test_logistics_factor_marts.py, tests/test_db_first_publication.py, tests/test_source_refresh.py, tests/test_web_app.py]
contracts: [wb_api_snapshot, unit_economics_report, ai_analysis_summary]
ai_sections:
  status: "Статус документа"
  goal: "Цель"
  scope: "Scope"
  sources: "Источники и границы чтения"
  probe: "Техническая проверка доступности источников"
  calculation: "Расчётная модель факторов"
  marts: "Расчётные витрины"
  api: "API"
  interface: "Интерфейс"
  acceptance: "Acceptance Criteria"
  tests: "Test Plan"
code_anchors:
  - path: src/wb_unit_economics/logistics_analysis.py
    symbols: ["def build_dimension_rows", "def build_measurement_rows", "def build_tariff_rows", "def build_route_rows"]
  - path: src/wb_unit_economics/wb_measurements.py
    symbols: ["def flatten_measurement_penalties", "def flatten_warehouse_measurements", "def export_wb_measurement_penalties", "def export_wb_warehouse_measurements"]
  - path: src/wb_unit_economics/wb_goods_return.py
    symbols: ["def normalize_goods_return_source_row", "def build_goods_return_links", "def export_wb_goods_return"]
  - path: scripts/probe_wb_logistics_factors.py
    symbols: ["def fetch_r0_source_payload", "def run_r0_identity_probe"]
  - path: src/wb_unit_economics/web/source_refresh.py
    symbols: ["def _record_wb_goods_return", "def _select_goods_return_snapshot", "def _build_and_persist_logistics_dimensions", "def _select_dimension_snapshot", "def _build_and_persist_logistics_measurements", "def _select_measurement_snapshot", "def _build_and_persist_logistics_tariffs", "def _select_tariff_snapshot", "def _build_and_persist_logistics_routes", "def _select_route_snapshot"]
  - path: src/wb_unit_economics/web/repository.py
    symbols: ["def replace_report_logistics_dimension_analysis", "def report_logistics_dimensions_payload", "def replace_report_logistics_measurement_analysis", "def report_logistics_measurements_payload", "def replace_report_logistics_tariff_analysis", "def report_logistics_tariffs_payload", "def replace_report_logistics_route_analysis", "def report_logistics_routes_payload"]
test_anchors:
  - path: tests/test_logistics_analysis.py
    symbols: ["def test_build_dimension_rows_links_by_nm_and_marks_unavailable"]
  - path: tests/test_web_app.py
    symbols: ["def test_logistics_dimensions_api_partial_coverage_uses_full_filtered_slice", "def test_logistics_dimensions_role_and_flag_matrix", "def test_logistics_measurements_api_states_filters_and_full_slice_coverage", "def test_logistics_measurements_role_and_flag_matrix", "def test_required_measurement_context_controls_publication_readiness", "def test_logistics_tariffs_api_partial_coverage_uses_full_filtered_slice", "def test_logistics_tariffs_role_and_flag_matrix", "def test_required_tariff_context_controls_publication_readiness", "def test_logistics_routes_api_partial_coverage_uses_full_filtered_slice", "def test_logistics_routes_role_and_flag_matrix", "def test_required_route_context_controls_publication_readiness"]
  - path: tests/test_source_refresh.py
    symbols: ["def test_goods_return_snapshot_db_and_file_authoritative_are_equivalent", "def test_goods_return_snapshot_integrity_failures_are_blocking", "def test_dimension_snapshot_db_and_file_authoritative_are_equivalent", "def test_dimension_snapshot_integrity_failures_are_blocking", "def test_measurement_snapshot_db_and_file_authoritative_are_equivalent", "def test_measurement_snapshot_integrity_failures_are_blocking", "def test_measurement_snapshot_precedence_partial_and_context_build", "def test_tariff_snapshot_db_and_file_authoritative_are_equivalent", "def test_tariff_snapshot_integrity_failures_are_blocking", "def test_tariff_snapshot_uses_primary_before_base_and_blocks_peer_conflict", "def test_tariff_context_and_rows_are_built_for_new_draft", "def test_route_snapshot_db_and_file_authoritative_are_equivalent", "def test_route_snapshot_integrity_failures_are_blocking", "def test_route_snapshot_uses_primary_before_base_and_blocks_peer_conflict", "def test_route_context_and_rows_are_built_for_new_draft"]
  - path: tests/test_wb_goods_return.py
    symbols: ["def test_goods_return_link_uses_finance_srid_and_one_canonical_return_chain", "def test_goods_return_link_rejects_cross_field_scope_and_chain_ambiguity"]
  - path: tests/test_wb_tariffs.py
    symbols: ["def test_build_tariff_snapshot_dates_uses_calendar_weeks", "def test_flatten_box_tariffs_keeps_period_and_none_for_missing"]
  - path: tests/test_logistics_factor_marts.py
    symbols: ["def test_build_measurement_rows_merges_exact_event_and_preserves_money", "def test_build_measurement_rows_isolates_cabinets_and_mapping_scope", "def test_build_measurement_rows_conflicts_fail_closed_without_fanout", "def test_measurement_analysis_is_atomic_and_published_report_is_immutable", "def test_build_tariff_rows_uses_historical_fact_and_current_estimate", "def test_build_route_rows_joins_exact_chain_and_marks_conflicts", "def test_route_analysis_is_atomic_and_published_report_is_immutable"]
  - path: tests/test_wb_measurements.py
    symbols: ["def test_measurement_penalties_pagination_reconciles_provider_total", "def test_flat_measurement_rows_omit_photos_and_subject_values", "def test_incomplete_measurement_page_fails_closed"]
  - path: tests/test_probe_wb_logistics_factors.py
    symbols: ["def test_f4_endpoints_are_read_only_minimal_and_cover_moscow_days", "def test_f4_status_aggregation_has_no_values_ids_labels_or_counts", "def test_claims_fetch_fails_closed_on_pagination_mismatch", "def test_run_r0_identity_probe_uses_all_claim_pages_and_keeps_r2_closed"]
depends_on: [workspace-shumeyko-partners-wb-logistics-cost-analysis-implementation]
rollout_required: true
updated_at: "2026-07-22"
---

# Статус документа

Статус — `accepted`. Это подчинённый accepted-спек второй очереди
(`WP-5 Факторы`) внутри truth_scope `logistics-cost-analysis`. Канонический
документ scope — accepted
[`docs/specs/wb-logistics-cost-analysis-implementation.md`](wb-logistics-cost-analysis-implementation.md)
(`truth_priority: 100`); при любом расхождении действует он. Этот спек не
является источником истины (`source_of_truth: false`) и не меняет формулы,
четыре категории классификации, порог `low_sample`, состав первой очереди или
границу факт/оценка/гипотеза. `accepted` означает согласованный дизайн; код и
тесты помечаются `implemented` только когда демонстрируемо соответствуют спеку.

Дизайн принят после живого read-only probe источников (2026-07-19, см.
[`docs/runbooks/wb-logistics-factors-probe.md`](../runbooks/wb-logistics-factors-probe.md)):
подтверждены тарифы box/pallet с периодами, goods-return с `reason`, а также
статистика склад/направление (по кабинету с полным scope). На 21.07.2026
официальный Reports contract повторно проверен для F-4: авторитетные read-only
источники — Analytics `measurement-penalties` и `warehouse-measurements`, а не
общий штраф Finance. Минимальный live source gate обоих методов пройден с
boolean-only evidence; raw, IDs, значения, суммы и counts не публиковались.

# Текущее состояние реализации

Первая очередь (`wb-logistics-v5`, фактический MVP) реализована; см. канонический
спек и
[`docs/runbooks/wb-logistics-v4-continuation.md`](../runbooks/wb-logistics-v4-continuation.md).

Реализованный читающий слой второй очереди:

- `src/wb_unit_economics/wb_content.py` — извлечение `dimensions` (габариты, вес,
  `isValid`) из карточек (F-1);
- `src/wb_unit_economics/wb_measurements.py` — read-only offset-pagination и
  безопасные flat snapshots двух Analytics endpoints (F-4);
- `src/wb_unit_economics/wb_tariffs.py` — read-only тарифы box/pallet с периодами
  действия (F-2);
- `src/wb_unit_economics/wb_goods_return.py` — read-only причины возврата
  продавцу (goods-return);
- `src/wb_unit_economics/wb_supplier_sales.py` — read-only склад отгрузки и
  направление доставки (F-3);
- `scripts/probe_wb_logistics_factors.py` — read-only probe доступности.

В `main` последовательно приняты additive schema, deterministic marts, verified
snapshot selectors, persistence, read-only API и staff-only UI F-1…F-4.

F-1 «Габариты» собран сквозным пакетом и принят на staff-only test 20 июля
2026 года: штатный report build выбирает и повторно проверяет авторитетный
snapshot карточек, атомарно сохраняет dimension context/mart, API реализует
state matrix, фильтры, SQL-pagination и coverage полного среза, а factor-блок
встроен в `#tables/logistics`. Operational evidence находится в
[`docs/runbooks/wb-logistics-v4-continuation.md`](../runbooks/wb-logistics-v4-continuation.md).
Статус всего factor-spec остаётся `accepted`: F-5 причины возвратов,
объединённая staff-приёмка всех factors, factor AI digest и
клиентский/production rollout остаются следующими подпакетами.

F-2 «Тарифы» реализован сквозным пакетом и принят на staff-only test 21 июля
2026 года: verified box/pallet snapshot, tariff context/mart, read-only
`/tariffs` и локальный UI-блок работают за отдельными defaults-off флагами.
Production и client enable не выполнялись.

F-3 «Склады и направления» принят на staff-only test 21 июля 2026 года:
verified `supplier/sales` snapshot, exact chain join, route context/mart,
read-only `/routes` и локальный UI-блок работают за отдельными defaults-off
флагами. Production и client enable не выполнялись.

F-4 «Замеры и удержания» реализован сквозным пакетом и принят на staff-only test
21 июля 2026 года: read-only collectors и verified dual snapshots,
нормализация/merge событий, immutable measurement context/mart, publication
readiness, read-only API и responsive UI работают за отдельными defaults-off
флагами. Финальный desktop wrap hotfix также принят; operational evidence
зафиксирован в runbook. Production и client enable не выполнялись.

F-5 «Причины возвратов» принят как отдельный spec-first контракт 22 июля 2026
года. Первый R-0I fail closed на DB/file ambiguity, а R-0L не нашёл пригодного
прежнего lineage. После отдельно разрешённого full source refresh новый
неопубликованный immutable draft получил verified file-authoritative Finance
без DB-строк и ambiguity. Повторный boolean-only R-0I подтвердил exact
`goods-return.srid → Finance.srid` и однозначную canonical return chain;
`goodsReturnIdentityGate=true`. Claims source keys в текущем окне отсутствуют,
поэтому `claimsIdentityGate=false`, `completeIdentityGate=false` и общий
`implementationGate=false`. Пользователь отдельно принял exact goods-return
`srid → Finance.srid` контракт; `goodsReturnImplementationGate=true`, поэтому
R-1 влит в `main` через PR №56 как registered
snapshot/selector/normalization/internal join без mart/API/UI и rollout.
Repeat live R-0I после merge PR №57 подтвердил полную provider-total pagination
без mismatch, но claims source keys в доступном окне отсутствуют. R-2 остаётся
закрыт до положительного identity evidence;
context/mart/API/UI и rollout автоматически не начинаются.

# Цель

Дать пользователю подтверждённые факторы, связанные с высокой стоимостью
логистики, не превращая гипотезы в факты. Ответить на третий вопрос сценария
(«какие подтверждённые факторы связаны с высокой стоимостью») из канонического
спека, оставаясь read-only и сохраняя явные статусы `Факт`, `Оценка`,
`Гипотеза` и `Данные недоступны`.

Вторая очередь добавляет к готовому фактическому блоку:

1. заявленные габариты и вес товара с упаковкой и сигнал расхождения карточки;
2. подтверждённые фактические замеры/удержания WB там, где Analytics Reports их
   содержит;
3. недельные коэффициенты логистики и хранения и периоды их действия;
4. склад отправления и доступное направление доставки, агрегаты по складам и
   маршрутам;
5. чёткое разделение подтверждённой причины, гипотезы и отсутствующих данных.

# Термины и обязательные трактовки

Термины первой очереди наследуются без изменений. Дополнительно:

- `Заявленные габариты` — длина/ширина/высота (см) и `weightBrutto` (кг) из
  карточки WB. Это значение, введённое продавцом, а не факт замера WB.
- `Сигнал расхождения` — флаг `isValid=false` в `dimensions` карточки. Он
  указывает на вероятное расхождение с категорийным средним, но НЕ содержит
  измеренных WB значений и сам по себе не является штрафом или фактом замера.
- `Фактический замер` — отдельная запись Analytics
  `warehouse-measurements` или `measurement-penalties` с измеренными WB
  габаритами. Это `Факт` источника, а не текущее состояние карточки.
- `Удержание за занижение габаритов` — `penaltyAmount` из
  `measurement-penalties`; `reversalAmount` хранится отдельно как отмена
  удержания. Общий `penalty` Finance не доказывает эту причину.
- `Чистое удержание F-4` — детерминированное
  `penaltyAmount - reversalAmount` без ограничения снизу. Это справочная
  производная Analytics, не бухгалтерская сверка и не новое слагаемое итоговой
  прибыли отчёта.
- `Коэффициент недели` — логистический/складской множитель WB, действующий на
  конкретной календарной неделе. Исторический коэффициент объясняет только свой
  период.
- `Направление доставки` — страна/округ/регион получателя из отчёта продаж.
- `Оценка` и `Гипотеза` трактуются как в каноническом спеке: оценка никогда не
  подменяет факт, гипотеза не показывается как установленная причина.

Заявленные габариты и текущий тариф не доказывают стоимость исторического
заказа. Историческое объяснение использует только данные и коэффициент
соответствующего периода, иначе вывод помечается как `Оценка`.

# Scope

## В scope второй очереди

- извлечение `dimensions` (габариты, вес, `isValid`) из уже загружаемых
  карточек WB и сохранение в плоском read-only слое, привязанном к `nmId`;
- чтение склада отправления и направления доставки на уровне продажи/заказа;
- коннектор тарифов WB box/pallet с сохранением периода действия
  (`dtNextBox`/`dtTillMax`) и складских коэффициентов;
- read-only сбор подтверждённых фактических замеров и удержаний из Analytics
  `measurement-penalties` и `warehouse-measurements` после live source gate;
- отдельные immutable `report_logistics_measurement_contexts` и
  `report_logistics_measurement_rows`, не меняющие F-1 dimension mart;
- витрины `report_logistics_dimension_rows` и `report_logistics_route_rows`;
- read-only API `/logistics/dimensions`, `/logistics/tariffs`,
  `/logistics/routes` и `/logistics/measurements`;
- блок факторов на первом экране логистики с явными статусами основания;
- детерминированные рекомендации по расхождению габаритов и дорогому
  направлению.

## Out Of Scope

Наследует Out Of Scope канонического спека. Дополнительно вне scope:

- любые write-методы WB, включая ответы покупателю `POST returns/claim` и
  обновление карточек товара;
- калькуляторы логистики и маржинального дохода (третья очередь);
- трактовка `isValid=false` как штрафа или доказанного расхождения;
- использование общего `penalty`/`bonusTypeName` Finance как замены F-4
  источника или автоматическое прибавление F-4 удержания к расходам отчёта;
- скачивание, публикация или передача в API/UI/AI `photoUrls` замеров;
- применение текущего тарифа к историческому периоду как факта;
- автоматическое изменение распределения товара по складам;
- Ozon и другие маркетплейсы.

# Источники и границы чтения

Все методы ниже read-only и вызываются токенами минимально необходимых
категорий (least privilege). Контракты F-1…F-4 повторно сверены с официальной
документацией WB на 21.07.2026. Документированный контракт подтверждает схему,
но не доступ конкретного токена, фактическую глубину истории и наличие строк;
эти свойства проверяются отдельным live probe без публикации raw.

## Габариты и вес — Content API

- `POST https://content-api.wildberries.ru/content/v2/get/cards/list`
  (токен категории «Контент»). Уже используется в `wb_content.py`.
- Поля: `dimensions.length`, `dimensions.width`, `dimensions.height` (см),
  `dimensions.weightBrutto` (кг), `dimensions.isValid` (сигнал расхождения).
- Пагинация курсором (`settings.cursor`: `nmID`, `updatedAt`, `limit`).
  Окна по датам нет — отдаётся текущее состояние карточки.

## Склад и направление — Statistics API

- `GET https://statistics-api.wildberries.ru/api/v1/supplier/sales`
  (токен «Статистика»): `warehouseName` (склад отгрузки), `countryName`,
  `oblastOkrugName`, `regionName` (направление), `srid`, `nmId`, `date`.
- `GET .../api/v1/supplier/orders` — склад и гео заказа.
- `GET .../api/v1/warehouse_remains` — уже используется в `wb_stocks.py`.
- Ограничения: обновление ~30 мин; хранение гарантировано не более 90 дней от
  даты продажи; отбор по `dateFrom`/`lastChangeDate`. Направление за более
  старый исторический период может быть недоступно — риск покрытия.

## Тарифы и коэффициенты — Tariffs API

- `GET https://common-api.wildberries.ru/api/v1/tariffs/box` и `/pallet`
  (раздел «Тарифы»): базовые ставки и коэффициенты логистики/хранения
  (`boxDeliveryBase`, `boxDeliveryLiter`, `boxDeliveryCoefExpr`,
  `boxStorageBase`, `boxStorageCoefExpr`, `warehouseName`), период действия
  `dtNextBox`/`dtTillMax`. Отдаёт текущие и архивные ставки.
- Историческая дата запрашивается обязательным query-параметром `date`
  (`YYYY-MM-DD`). Официальная документация WB на 21.07.2026 прямо определяет
  методы как источник текущих и архивных тарифов, но не гарантирует глубину
  архива; каждая запрошенная дата поэтому имеет отдельный статус сбора.
- `boxDeliveryCoefExpr`, `boxDeliveryMarketplaceCoefExpr` и
  `boxStorageCoefExpr` — проценты. WB указывает, что коэффициенты уже учтены в
  денежных ставках; F-2 показывает их как evidence и повторно не умножает
  денежный итог отчёта.
- `GET https://common-api.wildberries.ru/api/tariffs/v1/acceptance/coefficients`
  — коэффициенты приёмки по складам.
- Лимит зависит от типа токена: Personal/Service — 60 запросов в минуту на
  endpoint, Base — 1 запрос в час. Сбор выполняется последовательно, HTTP 429
  оставляет точку `data_unavailable`, а не обрезает период молча. Поле
  `dtFromMin` удалено WB 15.07.2026 — в парсер не закладывать.

## Фактические замеры и удержания — Analytics Reports

Авторитетные F-4 источники находятся в разделе официальных отчётов удержаний и
требуют токен категории «Аналитика»:

- `GET https://seller-analytics-api.wildberries.ru/api/analytics/v1/measurement-penalties`
  — отчёт о повышающем коэффициенте логистики и хранения из-за занижения
  габаритов. Поля: `nmId`, `subjectName`, `dimId`, `prcOver`, измеренные
  `volume/width/length/height`, заявленные
  `volumeSup/widthSup/lengthSup/heightSup`, `dtBonus`, `isValid`, `isValidDt`,
  `penaltyAmount`, `reversalAmount`, `photoUrls`;
- `GET https://seller-analytics-api.wildberries.ru/api/analytics/v1/warehouse-measurements`
  — отдельный отчёт складских замеров. Поля: `nmId`, `subjectName`, `dimId`,
  `volume/width/length/height`, `dt`, `photoUrls`.

Snapshot source types фиксируются как `wb_measurement_penalties` и
`wb_warehouse_measurements`; переименование требует новой methodology version.

Оба метода принимают optional `dateFrom`, обязательные `dateTo` и `limit <=
1000`, а также `offset`; документированный лимит — один запрос в минуту на
кабинет для каждого метода. Сбор обязан пройти все страницы до сверки с
provider `total`. Календарный период отчёта трактуется в `Europe/Moscow`, а в
WB передаётся полное покрывающее timestamp-окно. Фактическая глубина истории
provider contract не гарантирована и измеряется probe/manifest.

`photoUrls` остаются только в зашифрованном/защищённом raw snapshot согласно
общему retention. Collector не скачивает изображения; URL не попадает в flat,
mart, логи, API, UI, AI или operational evidence.

Finance `sales-reports/detailed` содержит общий `penalty` и
`bonusTypeName`, но не документирует измеренные габариты и не является
авторитетным F-4 источником. Он может использоваться позже только для отдельной
бухгалтерской сверки. F-4 v1 не связывает Analytics удержание с Finance строкой
по тексту, сумме или `nmId` и не добавляет его повторно в финансовые KPI.

## Read-only boundary

Новые write-методы во внешние системы запрещены. Внутренние снимки, витрины,
audit и retention — по действующим правилам tenant isolation. Раздельные rate
limits (tariffs 60/мин; статистика/аналитика/финансы — свои) требуют отдельного
бюджета запросов и backoff на HTTP 429.

# Техническая проверка доступности источников

До изменения расчётного и web-кода на авторизованном тестовом снимке без
публикации raw подтвердить по каждому источнику, к какому из трёх статусов он
относится: `подтверждён`, `частично/гипотеза`, `недоступен`.

Probe-чеклист:

1. Content: доля товаров среза с непустыми `dimensions` и распределение
   `isValid`. Габариты вообще заполнены?
2. Analytics F-4: отдельно вызвать `measurement-penalties` и
   `warehouse-measurements` с `limit=1` для каждого разрешённого кабинета;
   зафиксировать только HTTP/schema status, не значения и не число строк.
3. Tariffs: доступен ли архив за нужные исторические недели; какая самая ранняя
   дата отдаётся; совпадает ли `warehouseName` тарифа со складом продаж.
4. Statistics: покрытие `warehouseName` и направления за период отчёта; глубина
   90 дней достаточна для выбранных отчётов?
5. Join: связуемость `nmId`/`srid`/`warehouseName` между продажами, тарифами,
   карточками и финансовым фактом без дублирования сумм.
6. Замеры/удержания: проверить полную offset-pagination, согласованность
   provider `total`, timestamps, уникальность `(cabinet, dimId, nmId)` и
   возможность exact `(cabinet, nmId)` product mapping. Наличие ненулевого
   удержания не является условием доступности источника.

Результат probe фиксируется как обезличенная матрица доступности (аналог этапа
0 первой очереди) и определяет, какие подпункты scope включаются, а какие
переносятся или помечаются `Данные недоступны`. Источник, делающий требование
невыполнимым, не заполняется нулём и не подменяется гипотезой.

## Результаты probe по сохранённым данным (test, 2026-07-19)

Первый этап probe выполнен БЕЗ живых вызовов и без ключей — только агрегатный
осмотр уже сохранённых на test снимков (счётчики наличия полей, без сырых
значений). Живой probe тарифов, statistics и возвратов (нужны токены клиента
через приложение) ещё не выполнялся.

| Источник | Статус | Основание |
|---|---|---|
| Габариты/вес (Content) | ✅ подтверждён | Во всех сохранённых карточках есть `dimensions` (length/width/height), `weightBrutto` и `isValid`. |
| Платное хранение (paid_storage) | ✅ есть снимки | Сохранённые отчёты присутствуют. |
| Склад/направление | ❌ недоступен в сохранённом | В финансовом снимке нет `officeName`/`warehouseName`/гео — только `srid`; отчёт продаж с гео не сохраняется. Нужен новый live-источник Statistics `supplier/sales`. |
| Тарифы box/pallet | ❌ не подключено | В сохранённых данных тарифов нет; нужен новый live-коннектор. |
| Причины возвратов (goods-return/claims) | ❌ не подключено | В сохранённых данных отсутствуют; нужны новые live-коннекторы. |
| Замеры/удержания (Analytics Reports) | ✅ минимальный live gate | Оба Analytics GET-метода подтвердили schema хотя бы на одной разрешённой интеграции; evidence содержит только boolean-признаки без IDs, значений, сумм и counts. |

Следствие для порядка подпакетов: **F-1 (габариты)** разблокирован на уровне
источника и начат — извлечение `dimensions` в плоскую карточку реализовано
(read-only, `None` без подстановки нуля). F-3 (склад/маршруты), F-2 (тарифы) и
причины возвратов требуют живого read-only probe с ключами клиента до
реализации.

## Результат живого probe тарифов (2026-07-19)

Оба read-only метода `/box` и `/pallet` вернули HTTP 200 для двух разрешённых
кабинетов. Подтверждены обязательный `date`, `warehouseName`,
`boxDeliveryCoefExpr`, `palletDeliveryExpr`, `dtNextBox`, `dtNextPallet` и
`dtTillMax`. Raw и клиентские идентификаторы в evidence не записывались.
Глубина архива не считается гарантией: штатный сбор фиксирует успех или
недоступность каждой календарной недели отдельно.

## Source gate F-4 (2026-07-21)

Документированный API-контракт двух Analytics методов подтверждён. Это закрывает
ошибочную гипотезу о Finance как источнике замеров. Минимальный live probe
выполнен по runbook в отдельном read-only процессе: оба endpoint подтвердили
schema хотя бы на одной разрешённой интеграции, `schemaMismatchPresent=false`,
общий `implementationGate=true`. Gate считается пройденным, если по кабинетам
зафиксирован один из безопасных статусов `confirmed_empty`,
`confirmed_nonempty`, `access_denied` или `unavailable`, а успешный ответ
содержит ожидаемую envelope/schema. Raw строки, значения, `dimId`, `nmId`, URL
фото, суммы и клиентские объёмы не сохраняются в evidence.

`access_denied`/`unavailable` допускает реализацию с явным partial coverage для
этого кабинета. Несоответствие успешной schema официальному контракту
возвращает F-4 на spec review. Пройденный source gate не является rollout:
production не менялся, test deployment и staff-приёмка выполняются отдельно.

# Расчётная модель факторов

Модель наследует правила первой очереди и добавляет факторный слой без
изменения фактической суммы логистики и её классификации.

- Заявленные габариты и вес показываются как введённые продавцом значения.
  `isValid=false` показывается как `Сигнал`, а не факт замера.
- Фактический замер/удержание показывается как `Факт` только из подтверждённого
  Analytics Reports snapshot. `penaltyAmount` и `reversalAmount` хранятся
  отдельно; `net_penalty_amount = penalty_amount - reversal_amount` считается
  только когда оба значения валидны и неотрицательны. Результат не ограничивается
  нулём и не смешивается с базовой логистикой или общим `penalty` Finance.
- Размеры и объёмы F-4 — события на даты `dt`/`dtBonus`, а не текущее состояние
  карточки. Пустые, нечисловые и неположительные размеры/объёмы остаются
  `null`; явные нули денежных полей сохраняются. Контрольный объём считается
  только из трёх положительных размеров как `length * width * height / 1000` и
  округляется до 0,01 л `ROUND_HALF_UP`; он проверяет, но не заменяет provider
  `volume`/`volumeSup`.
- `prcOver` хранится как provider ratio `measuredVolume / declaredVolume *
  100`. Пользовательское превышение — nullable `prcOver - 100`; оно не
  пересчитывается из другого источника. `isValid` F-4 — сигнал конкретной
  Analytics-записи и не смешивается с одноимённым сигналом карточки F-1.
- Коэффициент недели связывается с календарной неделей операции. Для
  исторической недели применяется коэффициент того же периода; при отсутствии
  архива тариф на дату factor snapshot может быть показан только как
  `estimate`; историю им не объясняют и денежные KPI не пересчитывают.
- Недельная сетка F-2 строится по фактически присутствующим в SKU-mart
  `(cabinet, company, scheme, financial_week_start)`. Для каждой точки
  запрашиваются `box` и `pallet`; склад тарифа не связывается со складом
  операции до F-3.
- Направление и склад агрегируются на уровне `report_logistics_route_rows`;
  при нескольких значениях внутри цепочки возвращается `mixed`, а не первое
  случайное значение (как в order mart первой очереди).
- Каждый фактор несёт `evidenceType`: `fact`, `estimate`, `hypothesis` или
  `data_unavailable`; агрегаты факторов не складываются с денежным итогом
  логистики и помечаются как пересекающиеся срезы.
- Отрицательный коэффициент вознаграждения, `Микс`/`Моно` и разница
  цена-до-скидки/оплата НЕ считаются самостоятельным доказательством (см. Out
  Of Scope канона).

# Расчётные витрины

Витрины additive к опубликованному `report_id`, неизменяемы, хранят lineage до
`report_run`, версий методики/классификатора/ключа и hash входных данных.
Старый отчёт без них возвращает `needs_rebuild` и не достраивается на лету.

## `report_logistics_dimension_rows`

Гранулярность — товар (`product_ref`) в срезе отчёта. Поля: заявленные
габариты и вес, объём, `isValid`, фактический замер и штраф при наличии,
`evidenceType`, `coverage_status`, source hash. Финансовые поля nullable при
отсутствии подтверждённого источника.

F-1 строит ровно одну строку на
`tenant/client/cabinet/company/scheme/product_ref` в report run. Недельные SKU-
строки схлопываются детерминированно. Карточка связывается только по паре
`(wb_cabinet_id, nm_id)`; совпадение одного `nm_id` между кабинетами не является
связью. Одинаковые size-строки одной карточки схлопываются, а разные значения
дают `conflicting_dimensions` без случайного выбора.

Пустые, нечисловые и неположительные размеры/вес сохраняются как `null`.
Объём в литрах рассчитывается только из трёх положительных размеров как
`length_cm * width_cm * height_cm / 1000`. `isValid=false` остаётся сигналом
карточки, а `measured_penalty_amount` в F-1 всегда `null`.

`source_hash_digest` строки включает версию `wb-logistics-factors-v1`, полный
набор source hashes схлопнутых SKU-строк и hashes выбранных card rows.

## `report_logistics_dimension_contexts`

Один неизменяемый контекст на `report_run_id` хранит tenant/client,
`factor_methodology_version=wb-logistics-factors-v1`, `data_status`, полный
`input_hash`, snapshot hash и load timestamp Content, числа source/mart/matched/
missing/invalid/conflicting строк, а также безопасные blocking/review codes.

При включённом factor master-флаге report run получает
`logistics_dimensions_required=true`. Отсутствующий, устаревший или `blocked`
required context создаёт non-overridable publication blocker. Отсутствие
габаритов у товара создаёт mart row с `data_unavailable` и `partial`, но само по
себе публикацию не блокирует.

F-4 не обновляет и не расширяет опубликованные dimension rows. Историческое
событие замера не соответствует grain текущей карточки, поэтому существующее
`measured_penalty_amount` остаётся `null`; новые факты живут только в отдельной
measurement mart.

## `report_logistics_measurement_rows`

F-4 хранит одну immutable строку на provider-событие в report run с внутренним
grain `(tenant, client, wb_cabinet_id, dim_id, nm_id)`. `dim_id` и `nm_id`
нужны для воспроизводимости и exact join, но никогда не возвращаются наружу.
Строка содержит nullable report mapping (`client_company_id`, `scheme`,
`product_ref`), `event_kind=measurement_penalty|warehouse_measurement|merged`,
`measurement_at`, `penalty_effective_at`, `validation_at`, заявленные и
измеренные размеры/объёмы, provider ratio и derived excess, F-4 `is_valid`,
`penalty_amount`, `reversal_amount`, `net_penalty_amount`,
`accounting_reconciliation_status=unreconciled`, evidence/coverage/data-quality
statuses и source hash.

Сначала каждый endpoint нормализуется по `(wb_cabinet_id, dim_id, nm_id)`.
Полностью одинаковые повторы схлопываются. Разные значения одного ключа,
повторный `dim_id` с разными `nm_id` в одном кабинете или несовместимые размеры
между двумя endpoint дают `conflicting_measurement`; числовые поля конфликта не
выбираются случайно. Совпадение `dim_id` или `nm_id` в другом кабинете никогда
не является связью. Строки двух endpoints объединяются в `merged` только при
точном ключе и одинаковых общих измеренных значениях.

Product mapping выполняется только по `(wb_cabinet_id, nm_id)` к SKU-mart
этого report run. Недельные повторы одного и того же
`(company, scheme, product_ref)` схлопываются. Единственный distinct target даёт
exact mapping; отсутствие target даёт `unmatched_product`, несколько targets —
`ambiguous_product_scope`. Событие сохраняется с nullable mapping для coverage,
но не размножается по организациям/схемам и не дублирует сумму.

Пустые, нечисловые и неположительные размеры, объёмы и `prcOver` сохраняются
как `null`; отрицательные денежные source-значения считаются invalid, а явный
ноль сохраняется. `net_penalty_amount` nullable, если хотя бы одна денежная
компонента invalid/missing. Row hash включает `wb-logistics-measurements-v1`,
hashes точной SKU-группы и всех участвующих Analytics source rows. `photoUrls`,
`subjectName` и raw payload в mart не переносятся.

## `report_logistics_measurement_contexts`

Один immutable context на report run хранит tenant/client,
`factor_methodology_version=wb-logistics-measurements-v1`, `data_status`, полный
`input_hash`, отдельные hashes выбранных `wb_measurement_penalties` и
`wb_warehouse_measurements` snapshots, `factor_snapshot_at`, coverage window,
source/provider-total/mart event counts, число scoped products, matched,
unmatched, ambiguous, invalid, conflicting, penalty, reversal и warehouse-only
events, а также безопасные blocking/review codes. Денежные суммы не входят в
context/evidence.

Для каждого source type выбирается один авторитетный snapshot из lineage
`primary -> base -> contributor`. Две разные ревизии одного type и приоритета,
tenant/cabinet/window mismatch, DB/file ambiguity, неподтверждённый manifest,
изменившиеся flat hashes/provider total/row count или небезопасный путь создают
`blocked` context без mart rows. DB и `file_authoritative` обязаны давать
одинаковый результат. Успешный неполный endpoint, HTTP access failure или
неизвестная глубина истории дают `partial/data_unavailable`, но не подменяются
snapshot другого периода.

Context и rows сохраняются одной транзакцией только при создании нового draft;
published report не изменяется. При включённом measurements master-флаге report
получает `logistics_measurements_required=true`: missing/outdated/blocked
required context — non-overridable publication blocker. `partial` из-за
доступности источника или data-level conflict требует review, но публикацию не
блокирует.

## `report_logistics_tariff_rows`

F-2 хранит одну строку на
`tenant/client/cabinet/company/scheme/financial_week_start/tariff_type/warehouse`.
Поля: `requested_date`, дата тарифа, `box|pallet`, склад и geo label, ближайшая
дата изменения и конец доступного периода из ответа, nullable базовые ставки,
ставки дополнительного литра и коэффициенты доставки/хранения, отдельные FBS-
поля box, `evidence_type`, `coverage_status`, `data_quality_status` и source
hash. Денежные значения и проценты не входят в расчёт итоговой логистики.

Пустые, нечисловые и отрицательные значения остаются `null`; явный provider
zero сохраняется как ноль. Повторяющиеся строки одного склада с одинаковыми
значениями схлопываются. Разные значения одного business key дают
`conflicting_tariff` без случайного выбора. Архивная строка, полученная на
`financial_week_start`, имеет `evidence_type=fact`. Если точка архива
недоступна, допускается только явно выбранная строка снимка на дату сбора с
`evidence_type=estimate`; если нет и её, сохраняется placeholder
`data_unavailable`. Hash строки включает `wb-logistics-tariffs-v1`, hashes
SKU-группы и всех участвующих строк тарифа.

## `report_logistics_tariff_contexts`

Один immutable context на report run хранит tenant/client,
`factor_methodology_version=wb-logistics-tariffs-v1`, `data_status`, input и
snapshot hashes, factor snapshot timestamp, числа ожидаемых/фактических/
оценочных/недоступных cabinet-week-type точек, строк и складов, invalid/conflict
counts, безопасные blocking/review codes.

Источник выбирается из lineage `primary -> base -> contributor`. Две разные
ревизии одного приоритета, scope mismatch, DB/file ambiguity, неподтверждённый
manifest, изменившиеся hashes/row count или небезопасный путь создают
`blocked` context без tariff rows. DB и `file_authoritative` дают одинаковый
результат. Context и rows сохраняются атомарно только для нового draft;
published report не изменяется. При включённом tariff master-флаге report
получает `logistics_tariffs_required=true`: missing/outdated/blocked required
context — non-overridable publication blocker, `partial` из-за недоступного
архива — review и публикацию не блокирует.

## `report_logistics_route_rows`

F-3 хранит атомарную route evidence на уровне неизменяемого сегмента цепочки:
`tenant/client/cabinet/company/scheme/financial_date/product_ref/chain_key`.
Это storage-grain для корректных фильтров; API SQL-агрегирует его до склада и
направления доставки. Поля: дата и неделя, товар, склад, составное направление
`country/oblastOkrug/region`, статусы каждого поля, фактическая логистика
сегмента, `low_sample`, nullable box-коэффициент недели, отдельный статус
коэффициента, `evidence_type`, `coverage_status` и source hash.

Строка `supplier/sales` связывается только по точной тройке
`(wb_cabinet_id, srid, nm_id)` с chain key финансовой логистики. Совпадение
`srid` или `nm_id` отдельно, а также совпадение в другом кабинете не является
связью. Одинаковые строки одной цепочки схлопываются; разные непустые значения
склада или направления дают `mixed`, ничего не выбирается случайно. Пропуск
поля остаётся `missing`, не превращается в пустой маршрут или ноль.

Route mart сохраняет строку и для недоступного маршрута, чтобы полная
фактическая логистика среза и denominator coverage оставались
воспроизводимыми. Маршрут считается подтверждённым только когда оба поля имеют
status `ready`; `mixed`/`missing` получают `data_unavailable`. Поэтому
отдельного глобального порога нет: допустимость оценивается для каждой цепочки,
а валидные кабинеты не скрываются из-за частичного source scope другого
кабинета. Сумма `logistics_total` mart должна точно совпадать с order mart.

`week_coefficient` заполняется только из единственной непротиворечивой
исторической box-строки F-2 для той же недели, кабинета, организации, схемы и
нормализованного склада. Current estimate, pallet, missing/conflict или
неоднозначное имя склада оставляют коэффициент `null`; это не меняет
фактическую логистику. Hash строки включает `wb-logistics-routes-v1`, hashes
order segment, всех участвующих supplier-sales строк и связанной tariff-строки.

## `report_logistics_route_contexts`

Один immutable context на report run хранит tenant/client,
`factor_methodology_version=wb-logistics-routes-v1`, `data_status`, input и
snapshot hashes, factor snapshot timestamp и coverage window Statistics,
source/mart/total/matched/missing/conflicting chain counts, linked logistics,
warehouse/destination counts, reconciliation delta и безопасные
blocking/review codes.

Источник выбирается из lineage `primary -> base -> contributor`. Две разные
ревизии одного приоритета, scope mismatch, DB/file ambiguity, неподтверждённый
manifest, изменившиеся flat hashes/row count или небезопасный путь создают
`blocked` context без route rows. DB и `file_authoritative` дают одинаковый
результат. Context и rows сохраняются атомарно только для нового draft;
published report не изменяется. При включённом route master-флаге report
получает `logistics_routes_required=true`: missing/outdated/blocked required
context — non-overridable publication blocker, partial из-за недоступного
Statistics scope или неполной связки — review и публикацию не блокирует.

# API

Additive read-only методы, зарезервированные каноническим спеком; переиспользуют
авторизацию, tenant boundary, роли, пагинацию и фильтры кабинета:

- `GET /api/reports/{report_id}/logistics/dimensions` — вторая очередь;
- `GET /api/reports/{report_id}/logistics/measurements` — F-4;
- `GET /api/reports/{report_id}/logistics/tariffs` — F-2;
- `GET /api/reports/{report_id}/logistics/routes` — вторая очередь.

Ответы содержат те же служебные поля, что и методы первой очереди
(`dataStatus`, `sliceStatus`, `coverage`, версии, `generatedAt`,
`sourceCoverageEnd`), плюс покрытие факторов и признак факт/оценка/гипотеза для
каждого блока. Отсутствие фактора возвращает явный `data_unavailable`, а не
нулевую подстановку. Пустой разрешённый срез — `sliceStatus=empty` без нулей.
Старый отчёт без новых витрин — `needs_rebuild`.

Контракт F-1 `/dimensions`:

- фильтры `periodStart`, `periodEnd`, `wbCabinetId`, `clientCompanyId`, `scheme`,
  `product`; период определяет товары, присутствующие в логистическом срезе;
- SQL-pagination `offset`/`limit` и сортировки `product`, `volumeL`,
  `weightBruttoKg`, `coverageStatus`;
- поля `dataStatus`, `sliceStatus`, `methodologyVersion`,
  `factorMethodologyVersion`, `generatedAt`, `sourceCoverageEnd`,
  `factorSnapshotAt`, `filterContext`, `coverage`, `rows`, `total`, `offset`,
  `limit`, `recommendations`;
- `coverage` и рекомендации рассчитываются по полному фильтрованному срезу, а
  не по текущей странице;
- `needs_rebuild` — нет совместимого context; `blocked` — нарушена целостность
  или scope; `empty` — в разрешённом срезе нет товаров; `partial` — есть
  missing/invalid/conflicting; иначе `ready`.

Габариты всегда подписываются как текущее состояние карточки на
`factorSnapshotAt`, а не как исторический замер. Raw payload, source hashes и
seller account identifiers в ответ не входят.

Контракт F-4 `/measurements`:

- фильтры `periodStart`, `periodEnd`, `wbCabinetId`, `clientCompanyId`,
  `scheme`, `product`, `eventKind`, `hasPenalty`; период относится к дате
  события F-4 (`penaltyEffectiveAt`, иначе `measurementAt`) в
  `Europe/Moscow`, а не к неделям финансовой логистики и не к дате карточки;
- SQL-pagination `offset`/`limit`; сортировки `eventDate`, `product`,
  `volumeRatioPercent`, `penaltyAmount`, `netPenaltyAmount`, `coverageStatus`;
- поля `dataStatus`, `sliceStatus`, `methodologyVersion`,
  `factorMethodologyVersion`, `generatedAt`, `sourceCoverageStart`,
  `sourceCoverageEnd`, `factorSnapshotAt`, `filterContext`, `coverage`, `rows`,
  `total`, `offset`, `limit`, `recommendations`, `accountingTreatment`;
- безопасная row содержит report product label/ref, `eventKind`, даты замера и
  удержания, заявленные и измеренные размеры/объёмы, provider ratio, derived
  excess, безопасный F-4 validation signal, `penaltyAmount`, `reversalAmount`,
  `netPenaltyAmount`, `accountingReconciliationStatus`, evidence/coverage
  statuses. Raw `dimId`, `nmId`, `photoUrls`, hashes, subject/account/seller IDs
  не возвращаются;
- `coverage` считается SQL по полному фильтрованному срезу до pagination:
  expected/complete/unavailable endpoints, scoped products, products with
  events, total/penalty/reversal/warehouse-only events, matched/unmatched/
  ambiguous/invalid/conflicting events и `measurementIncidencePercent`;
- низкая доля товаров с событиями не является неполнотой: WB не обязан
  измерять каждый товар. `needs_rebuild` — нет совместимого context; `blocked`
  — integrity/scope/row-count failure; `empty` — источники полностью собраны,
  но в разрешённом срезе нет событий; `partial` — неполный источник или есть
  invalid/conflicting/unmatched/ambiguous события; иначе `ready`;
- `accountingTreatment` всегда объясняет, что суммы являются фактом Analytics,
  пока `unreconciled` не прибавляются к итоговой прибыли/убытку и не заменяют
  общий штраф Finance. Explicit zero остаётся нулём, missing остаётся `null`.

Контракт F-2 `/tariffs`:

- фильтры `periodStart`, `periodEnd`, `wbCabinetId`, `clientCompanyId`,
  `scheme`, `warehouse`, `tariffType`; SQL-pagination `offset`/`limit`;
- сортировки `requestedDate`, `warehouse`, `deliveryCoefficient`,
  `storageCoefficient`, `coverageStatus`;
- служебные поля F-1 плюс `filterContext`, coverage полного фильтрованного
  среза, `rows`, `total`, `offset`, `limit`, `recommendations`;
- coverage считает все cabinet-week-type точки до pagination: expected,
  factual, estimated, unavailable, invalid, conflicts, warehouses и процент
  фактического покрытия;
- старый/несовместимый context — `needs_rebuild`, integrity/scope failure —
  `blocked`, разрешённый срез без недель — `empty`, estimate/missing/invalid/
  conflict — `partial`, полное архивное покрытие — `ready`;
- строка явно содержит `requestedDate`, `tariffDate`, `evidenceType` и
  предупреждение, что это справочный тариф без денежного эффекта. Raw,
  source hashes, account IDs и внутренние row IDs не возвращаются.

Контракт F-3 `/routes`:

- фильтры `periodStart`, `periodEnd`, `wbCabinetId`, `clientCompanyId`, `scheme`,
  `product`, `warehouse`, `destination` применяются до SQL-агрегации;
- SQL-pagination `offset`/`limit` и сортировки `warehouse`, `destination`,
  `logisticsTotal`, `chainCount`, `coverageStatus`;
- поля `dataStatus`, `sliceStatus`, `methodologyVersion`,
  `factorMethodologyVersion`, `generatedAt`, `sourceCoverageStart`,
  `sourceCoverageEnd`, `factorSnapshotAt`, `filterContext`, `coverage`, `rows`,
  `total`, `offset`, `limit`, `recommendations`;
- строка API содержит только безопасные warehouse/destination labels,
  фактическую логистику, chain count, `lowSample`, nullable week coefficient,
  coefficient/evidence/coverage statuses; raw `srid`, `nmId`, chain/hash и
  seller identifiers наружу не возвращаются;
- `coverage` и рекомендации считаются по полному фильтрованному срезу до
  pagination: total/matched/missing/conflicting chains, linked/unlinked
  logistics, warehouse/destination counts и coverage percent;
- `needs_rebuild` — нет совместимого context; `blocked` — integrity/scope или
  reconciliation failure; `empty` — в разрешённом срезе нет route evidence;
  `partial` — есть missing/conflicting; иначе `ready`.

# Интерфейс

Блок факторов встраивается в существующий answer-first экран логистики
(`#tables/logistics`) как второй уровень, не создавая отдельного пункта меню и
не меняя денежный итог первого экрана.

- Показывает габариты/вес, сигнал расхождения, подтверждённые замеры/удержания,
  коэффициенты, склады и направления только при подтверждённом источнике.
- Явно маркирует основание каждой строки: `Факт`, `Оценка`, `Гипотеза`,
  `Данные недоступны`. Строки факторов помечены как пересекающиеся срезы и не
  воспринимаются как слагаемые одного итога.
- При отсутствии источника пишет `Данные недоступны`, а не выводит гипотезу как
  факт. Причина возврата без отдельного источника остаётся `Причина недоступна
  в Finance` (правило первой очереди).
- Технические поля, полные габариты и маршрутные детали — в disclosure/
  drill-down; клиенту показываются разрешённые бизнес-поля без raw payload и
  внешних идентификаторов.
- На mobile глобальные фильтры не скрываются; карточки факторов переходят в
  подписанный вертикальный layout.

Согласованный синтетический visual target F-1 зафиксирован в
[`docs/design/wb-logistics-f1-dimensions-target.html`](../design/wb-logistics-f1-dimensions-target.html).

Для F-1 target фиксирует секцию `Факторы стоимости -> Габариты в карточке WB`
после финансовой аналитики и до рейтинга товаров: coverage, размеры, объём,
вес, сигнал карточки и явное предупреждение, что значения не меняют денежный
итог. На mobile строки становятся подписанными карточками. Factor API error не
ломает первую очередь и отображается локальным безопасным состоянием.

Доступ F-1 управляется двумя отдельными defaults-off флагами:
`SHUMEYKO_LOGISTICS_FACTORS_ENABLED` и
`SHUMEYKO_LOGISTICS_FACTORS_CLIENT_ENABLED`. Staff требует master-флаги первой
и второй очереди. Client дополнительно требует оба client-флага; при отказе API
возвращает HTTP 404, UI не делает запрос и не показывает секцию.

Синтетический target F-4 фиксируется в
[`docs/design/wb-logistics-f4-measurements-target.html`](../design/wb-logistics-f4-measurements-target.html).
Секция `Факторы стоимости -> Контрольные замеры и удержания WB` идёт сразу
после F-1 габаритов, до тарифов и маршрутов: source completeness, число событий
и затронутых товаров, заявленные/измеренные размеры, ratio/excess,
удержание/отмена/чистая справочная сумма и reconciliation status. Отсутствие
события у товара не подписывается как пропуск данных. Суммы визуально отделены
от финансового итога предупреждением о возможном двойном учёте. Raw IDs, URL
фото и hashes не выводятся; на mobile строки становятся подписанными карточками.

F-4 закрыт defaults-off флагами
`SHUMEYKO_LOGISTICS_MEASUREMENTS_ENABLED` и
`SHUMEYKO_LOGISTICS_MEASUREMENTS_CLIENT_ENABLED`. Staff требует master-флаги
логистики/factors и measurements master. Client дополнительно требует client-
флаги логистики/factors/measurements. При запрете API возвращает 404, UI не
выполняет запрос. Ошибка measurement API отображается локально и не ломает
F-1/F-2/F-3 или первую очередь; состояние сбрасывается при смене report/filter.

Синтетический target F-2 фиксируется в
[`docs/design/wb-logistics-f2-tariffs-target.html`](../design/wb-logistics-f2-tariffs-target.html).
Секция `Факторы стоимости -> Тарифы и коэффициенты WB` идёт после габаритов и
F-4 замеров, до рейтинга товаров: coverage по неделям, дата запроса, склад, box/pallet,
коэффициенты доставки/хранения и метка `Факт`/`Оценка`/`Данные недоступны`.
На mobile строки становятся подписанными карточками. Ошибка tariff API
локальна и не ломает габариты или первую очередь.

F-2 дополнительно закрыт defaults-off флагами
`SHUMEYKO_LOGISTICS_TARIFFS_ENABLED` и
`SHUMEYKO_LOGISTICS_TARIFFS_CLIENT_ENABLED`. Staff требует master-флаги
логистики/factors и tariff master. Client дополнительно требует все три
client-флага. При запрете API возвращает 404, UI не выполняет запрос.

Синтетический target F-3 фиксируется в
[`docs/design/wb-logistics-f3-routes-target.html`](../design/wb-logistics-f3-routes-target.html).
Секция `Факторы стоимости -> Склады и направления` идёт после тарифов и до
рейтинга товаров: coverage цепочек, склад, направление, фактическая логистика,
число цепочек, `lowSample` и nullable исторический box-коэффициент. Hashes,
raw identifiers и внешние seller IDs не выводятся. На mobile строки становятся
подписанными карточками. Ошибка route API локальна и не ломает F-1/F-2 или
денежную аналитику первой очереди.

F-3 дополнительно закрыт defaults-off флагами
`SHUMEYKO_LOGISTICS_ROUTES_ENABLED` и
`SHUMEYKO_LOGISTICS_ROUTES_CLIENT_ENABLED`. Staff требует master-флаги
логистики/factors и route master. Client дополнительно требует client-флаги
логистики/factors/routes. При запрете API возвращает 404, UI не выполняет
запрос и не показывает секцию.

# Правила рекомендаций

Наследуют формат первой очереди (`code`, `priority`, `title`, `message`,
nullable `impactAmount`, `evidenceType`, `actionTarget`, `actionLabel`,
`evidence`; сортировка по priority, затем по убыванию `|impactAmount|`).
Добавляются флаги:

- подтверждённое расхождение габаритов → проверить упаковку и данные карточки
  (`evidenceType=fact` только при валидном F-4 замере, иначе `limitation`);
- `penaltyAmount > 0` → проверить упаковку и заявленные габариты; сумма
  показывается в evidence, но `impactAmount=null`, пока нет точной Finance
  reconciliation;
- `reversalAmount > 0` → проверить итог удержания в финансовой сверке
  (`evidenceType=fact`, `impactAmount=null`);
- invalid/conflicting/unmatched/ambiguous F-4 событие или недоступный endpoint →
  проверить источник/связку (`evidenceType=data_unavailable`, без денежного
  эффекта);
- высокий расход на конкретном направлении → проверить распределение запасов;
- `isValid=false` карточки без совпавшего валидного F-4 события → пометка
  ограничения, не факт замера или удержания.

Лидеры выбираются SQL по полному фильтрованному срезу, не из top-10 общего
рейтинга.

# AI Boundary

Наследует канонический AI Boundary. AI получает только рассчитанные факторные
витрины и разрешённые evidence-поля; не читает raw payload, не придумывает
причину возврата, не объявляет товар убыточным по одному фактору или
коэффициенту, не подставляет отсутствующее значение нулём. AI обязан разделять
`Факт`, `Оценка`, `Гипотеза` и `Данные недоступны`.
F-4 не передаёт AI `photoUrls`, raw identifiers или суммы как потенциальную
экономию; до reconciliation модель получает явный `includedInFinancialKpi=false`.

# Ошибки и пограничные случаи

- Нет `dimensions` в карточке → фактор габаритов `data_unavailable`, gate не
  блокируется.
- `isValid=false` в карточке без валидного F-4 события → только сигнал, не замер
  и не удержание.
- Полностью собранный F-4 источник без событий → `empty`, а не missing и не
  доказательство отсутствия будущих замеров.
- Низкая incidence событий по товарам → не `partial`; `partial` создают только
  неполный сбор или проблемные возвращённые события.
- Одинаковый F-4 event в двух endpoints с одинаковыми значениями → одна merged
  row; разные значения → `conflicting_measurement` без случайного выбора.
- Событие без единственной exact `(cabinet, nmId)` связи сохраняется в coverage
  как unmatched/ambiguous и не размножает удержание по компаниям/схемам.
- Missing/invalid/negative money → `null`; provider zero сохраняется; derived
  net не ограничивается нулём и не включается в financial KPI.
- HTTP 401/403/429 или неполная pagination отдельного F-4 endpoint → безопасный
  `partial/data_unavailable`; успешный verified empty endpoint остаётся empty.
- Нет исторического тарифа за нужную неделю → коэффициент показывается как
  `Оценка` по явно выбранному тарифу, историю им не объясняют.
- Нет направления доставки → route mart сохраняет строку цепочки с
  `data_unavailable`, чтобы coverage и reconciliation не теряли знаменатель.
- Несколько складов/направлений в одной цепочке → `mixed`, а не первое
  значение.
- Разные rate limits источников → после первого 429 серия запросов этого
  токена останавливается, оставшиеся даты получают безопасный статус, а
  частичный сбор помечается `partial`, а не тихо обрезается.
- Общий Finance `penalty` не связывается с F-4 по сумме/тексту/товару и не
  подменяет отсутствующий Analytics endpoint.
- Новая обязательная витрина со статусом `blocked`/устаревшей методикой →
  publication blocker, как в первой очереди.
- DB/file ambiguity, изменившийся manifest/hash/row count, выход raw path за
  разрешённый root, foreign tenant/client/cabinet и две разные ревизии Content
  одинакового lineage-приоритета → `blocked`; dimension rows не сохраняются.
- Для Content выбирается один полный snapshot по приоритету
  `primary -> base -> contributor`. Частичный snapshot не дополняется старыми
  строками другой ревизии: доступные товары показываются, остальные получают
  `data_unavailable`.
- Тарифные snapshot conflict/integrity/scope обрабатываются теми же fail-closed
  правилами lineage, но с кодами `tariff_*`; при `blocked` строки не
  сохраняются.
- Успешная историческая дата без отдельного склада означает отсутствие этого
  склада в том ответе; F-2 не дополняет её складом из другой архивной даты.
- Supplier-sales snapshot conflict/integrity/scope обрабатываются теми же
  fail-closed правилами с кодами `route_*`; при `blocked` строки не
  сохраняются.
- Statistics хранит ограниченную историю: непокрытая часть периода даёт
  `partial/data_unavailable`, не подменяется текущим маршрутом и сама по себе не
  блокирует публикацию.
- Один `srid` с разными `nm_id`, одинаковый `srid` другого кабинета и строка
  без точного product key не связываются по fallback.
- Measurement snapshot conflict/integrity/scope обрабатывается fail-closed с
  кодами `measurement_*`; `blocked` context не содержит mart rows. Data-level
  invalid/conflict остаётся reviewable `partial`, а не integrity blocker.

# Безопасность и tenant isolation

- Каждый запрос ограничен tenant/client/cabinet доступами пользователя.
- Внешние интеграции остаются read-only; write-методы (ответ покупателю,
  обновление карточек) запрещены.
- Raw payload, токены и секреты не возвращаются интерфейсу и AI.
- `photoUrls` не скачиваются и не покидают защищённый raw слой; operational
  evidence не содержит IDs, сумм, размеров, URL или client counts.
- Действующие audit, session, retention и backup правила применяются без
  ослабления.

# Этапы реализации

Соответствует `WP-5 Факторы` канонического спека и разбивается на подпакеты:

1. `F-0 Probe доступности` — обезличенная матрица доступности источников на
   реальном снимке; определяет включаемый состав.
2. `F-1 Габариты` — извлечение `dimensions` из карточек, витрина
   `report_logistics_dimension_rows`, API `/dimensions`, блок UI.
3. `F-2 Тарифы и коэффициенты` — коннектор box/pallet с периодами действия,
   verified исторические snapshots, tariff context/mart, `/tariffs` и
   staff-only UI.
4. `F-3 Склады и маршруты` — направление/склад из продаж, витрина
   `report_logistics_route_rows`, API `/routes`, агрегаты.
5. `F-4 Замеры и удержания` — отдельный source gate двух Analytics GET,
   verified snapshots, `wb-logistics-measurements-v1` context/mart,
   `/measurements` и staff-only UI без повторного финансового учёта.
6. `F-5 Приёмка и rollout` — staff-only проверка за флагом, затем отдельное
   решение о клиентском включении.

Каждый подпакет реализуется за выключенным флагом и additive-миграцией схемы;
последовательность после F-0 уточняется матрицей доступности.

# Acceptance Criteria

Design-часть подпакета считается принятой, когда владелец подтвердил состав MVP
факторов и разделение факт/оценка/гипотеза/недоступно. Реализация второй
очереди считается готовой, когда:

1. probe зафиксировал доступность каждого источника обезличенной матрицей, и
   недоступные факторы явно помечены `data_unavailable`, а не заполнены нулём;
2. заявленные габариты и `isValid` показаны как значение продавца/сигнал, а не
   как факт замера WB;
3. фактический замер/удержание показан как `Факт` только при подтверждённом
   Analytics Reports источнике и не смешан с базовой логистикой или Finance;
4. исторический период объясняется только коэффициентом своего периода; текущий
   тариф помечается `Оценка`;
5. маршрутная и dimension-витрины трассируются до source hashes и версий;
6. фильтры дают согласованные факторные агрегаты; несколько значений в цепочке
   дают `mixed`;
7. пользователь одного tenant не получает данные другого;
8. старый отчёт без новых витрин возвращает `needs_rebuild`;
9. AI не получает raw payload и не выдаёт гипотезу за факт;
10. ни один сценарий не выполняет запись во внешнюю систему.
11. dimension context и rows воспроизводимы из одинакового DB- или
    file-authoritative snapshot с одинаковым `input_hash`;
12. повторяющиеся недельные SKU и size-строки не дублируют mart, одинаковый
    `nm_id` другого кабинета не связывается;
13. factor API и UI закрыты отдельной staff/client role matrix, а ошибка F-1 не
    скрывает и не меняет денежную аналитику первой очереди.
14. F-2 хранит факт только для явно запрошенной исторической даты, current
    fallback маркирует `estimate`, а coverage считается до pagination.
15. tariff context/rows атомарны, published report immutable, required
    blocked/missing/outdated context блокирует публикацию, partial — нет.
16. F-3 связывает Statistics только по `(cabinet, srid, nm_id)`, сохраняет
    missing/mixed явно и полностью reconciles route logistics с order mart.
17. route coverage считается до pagination, API/UI не возвращают raw IDs или
    hashes, а локальная ошибка F-3 не ломает F-1/F-2 и первую очередь.
18. route context/rows атомарны, published report immutable, required
    blocked/missing/outdated context блокирует публикацию, partial — нет.
19. F-4 source gate отдельно проверяет оба Analytics endpoint для каждого
    разрешённого кабинета и не публикует raw, IDs, значения, суммы или counts.
20. Measurement snapshot selection воспроизводим для DB/file-authoritative;
    integrity/scope/provider-total failure даёт blocked context без rows.
21. F-4 не дублирует событие между endpoints и организациями, связывает товар
    только по кабинету и `nmId`, а conflicts/unmatched/ambiguous оставляет явными.
22. `/measurements` реализует filters/sorts/SQL-pagination, full-slice coverage
    и различает source completeness от incidence; пустой полный источник даёт
    `empty`, а низкая incidence не даёт `partial`.
23. F-4 суммы хранятся как source fact и nullable derived net, но до exact
    Finance reconciliation имеют `includedInFinancialKpi=false`; общий
    `penalty` не используется как fallback.
24. Measurement context/rows атомарны, published report immutable, required
    missing/outdated/blocked context блокирует публикацию, partial — нет;
    defaults-off role/flag matrix и локальная UI error isolation соблюдены.

# Test Plan

- unit: извлечение `dimensions`/`weightBrutto`/`isValid` из карточки, включая
  отсутствующий объект и `isValid=false`;
- unit: привязка коэффициента недели к периоду; отсутствие архива → `Оценка`;
- unit: календарная сетка дат, locale Decimal, explicit zero, missing/invalid/
  negative, одинаковые и конфликтующие tariff rows, стабильность hashes;
- unit: агрегация склад/направление, `mixed` при конфликте;
- unit: exact `(cabinet, srid, nm_id)` join, одинаковый `srid` между кабинетами,
  duplicate/conflicting supplier-sales, missing route, стабильность hashes,
  order/route logistics reconciliation и nullable historical box coefficient;
- unit: `evidenceType` факторов и запрет нулевой подстановки;
- unit F-4: pagination/provider-total, одинаковые и конфликтующие `dimId`,
  изоляция кабинетов, deterministic merge двух endpoints, exact/ambiguous/
  unmatched product mapping, timestamp boundaries и стабильность hashes;
- unit F-4: missing/invalid/non-positive размеры и объёмы, explicit monetary
  zero, invalid negative money, контрольный объём `ROUND_HALF_UP`, provider
  ratio/excess, nullable net и отсутствие clamp;
- integration: сборка витрин `report_logistics_dimension_rows` и
  `report_logistics_route_rows` из обезличенного снимка, lineage и hash;
- API: `/dimensions` и `/routes` возвращают статусы, покрытие и факт/оценку;
  пустой срез → `empty`; старый отчёт → `needs_rebuild`;
- tenant isolation: недоступность чужих tenant/cabinet во всех новых методах;
- fixtures обезличенные; реальные идентификаторы и клиентские объёмы в тесты и
  документацию не переносятся.
- source integration: DB/file parity, lineage precedence, raw integrity/path,
  storage ambiguity и tenant scope;
- persistence/API: atomic tariff context+rows, published immutability,
  row-count reconciliation, все states/filters/sort/pagination, full-slice
  coverage, role/flag matrix и отсутствие raw/hash полей;
- persistence/API: atomic route context+rows, published immutability,
  reconciliation, publication blocker, role/flag matrix, filters,
  SQL-pagination/sorting и coverage полного среза;
- source integration F-4: DB/file parity отдельно для двух source types,
  primary/base/contributor precedence, manifest/path/hash/row-count/provider-
  total mismatch, storage ambiguity, tenant/cabinet/window mismatch, partial
  endpoint и запрет скачивания/экспозиции `photoUrls`;
- persistence/API F-4: atomic measurement context+rows, published immutability,
  required-context blocker, все states/filters/sorts/SQL-pagination, coverage до
  страницы, incidence semantics, tenant/role/flag matrix, 404 и отсутствие raw/
  hash/ID/photo данных;
- UI F-4: load/reset при смене report/filter, ready/partial/empty/needs_rebuild/
  blocked/error, mobile cards, отсутствие трактовки суммы как нового расхода
  или потенциальной экономии;
- browser: staff-only deep-link на desktop/mobile, client 404/скрытый блок,
  отсутствие overflow и console/page/network errors.

Файлы: `tests/test_probe_wb_logistics_factors.py`,
`tests/test_wb_measurements.py`, `tests/test_logistics_factor_marts.py`,
`tests/test_source_refresh.py`, `tests/test_web_app.py` и существующие factor-
тесты F-1…F-3. Все fixtures обезличены.

# Rollout And Rollback

1. Выполнить F-0 probe в staff-only test без публикации raw.
2. Собрать доступные факторные витрины для одного репрезентативного отчёта.
3. Включить факторный блок consultant/admin за отдельным feature flag без
   клиентской публикации.
4. После приёмки — отдельное решение о клиентском включении.

Для F-1 на test включается только
`SHUMEYKO_LOGISTICS_FACTORS_ENABLED=true`; client-флаг остаётся `false` даже
если клиентская первая очередь уже включена. Требуется новый immutable report
run из verified snapshot. Production в этот rollout не входит.

Для F-2 сначала применяется additive migration и immutable runtime. На test
включаются factor master и `SHUMEYKO_LOGISTICS_TARIFFS_ENABLED`; оба client-
флага остаются `false`. Новый report run строится из verified tariff snapshot,
после чего staff API/UI проверяются на desktop 1440x900 и mobile 390x844.
Client API обязан вернуть 404, секция отсутствовать. Production и client
enable не выполняются; operational evidence не содержит объёмов, складов или
идентификаторов клиента.

Для F-3 применяется additive migration и immutable runtime. На test включаются
factor master и `SHUMEYKO_LOGISTICS_ROUTES_ENABLED`; route client-флаг остаётся
`false`. Новый report run строится из verified supplier-sales snapshot,
staff API/UI проверяются на desktop 1440x900 и mobile 390x844. Client API
обязан вернуть 404, секция отсутствовать. Production и client enable не
выполняются; operational evidence не содержит объёмов, складов, направлений или
идентификаторов клиента.

Для F-4 live source gate двух Analytics GET выполнен до product-кода без
сохранения raw в evidence. После merge применяются additive migration и
immutable runtime. На test включаются factor master и
`SHUMEYKO_LOGISTICS_MEASUREMENTS_ENABLED`; measurements client-флаг остаётся
`false`. Новый immutable report строится из verified snapshots с полной
provider-total reconciliation. Staff API/UI проверяются на desktop 1440x900 и
mobile 390x844; client API возвращает 404, секция отсутствует, browser не имеет
overflow/console/page/network errors. В evidence записываются только дата,
revision/runtime identity, flags, schema/methodology states и результат
проверок — без клиентских counts, IDs, размеров, сумм, складов и URL фото.
Production, client enable и финансовая агрегация F-4 не выполняются.

Rollback отключает новые API-маршруты и факторный блок, не изменяя существующие
отчёты и первую очередь. Новые витрины additive и неизменяемы. Внешние источники
при rollout и rollback не изменяются. Отключение флага не снимает publication
blocker с report run, который обязан был пройти gate, но не прошёл.

# Согласованные решения

Решения приняты после probe и официальной сверки контрактов 2026-07-19…21:

1. Заявленные габариты и `isValid` — это значение продавца и сигнал; фактом
   замера считается только подтверждённый Analytics Reports источник.
2. Исторический тариф/коэффициент берётся по периоду; текущий — только
   `Оценка`.
3. F-4 читает `measurement-penalties` и `warehouse-measurements`. Общий Finance
   `penalty` не является источником причины и не используется как fallback.
4. Витрины factors additive и неизменяемы; отсутствие фактора не заполняется
   нулём.
5. Блок факторов встраивается в существующий экран логистики, без отдельного
   пункта меню.
6. Калькуляторы остаются третьей очередью и в этот draft не входят.
7. F-4 сохраняется отдельной event mart; dimension mart текущей карточки не
   дополняется историческими замерами.
8. `penaltyAmount`, `reversalAmount` и derived net показываются как справочный
   факт Analytics с `includedInFinancialKpi=false` до exact Finance
   reconciliation; текстовый или суммовой fuzzy join запрещён.
9. Полнота источника и incidence событий — разные метрики. Полный пустой ответ
   даёт `empty`; отсутствие замера у большинства товаров не означает partial.

# Открытые вопросы

- Фактическая retention/history depth двух F-4 Analytics endpoint не
  гарантирована provider contract и фиксируется coverage window каждого
  verified snapshot; минимальный live schema gate уже пройден.
- Exact бухгалтерское соответствие Analytics удержания строке Finance не
  документировано. Оно не входит в F-4 v1; до отдельного accepted решения суммы
  не включаются повторно в financial KPI.
- Глубина архива тарифов не гарантирована provider contract и измеряется
  статусами отдельных дат, а не считается настройкой F-2.
- Отдельный retention для tariff snapshot не вводится: действует retention
  source-refresh, а опубликованный report хранит только нормализованный mart.

Закрытые probe и staff-приёмка (2026-07-19…21): F-1, F-2, F-3 и F-4 приняты на
staff-only test; production/client enable не выполнялся. Для F-5 новый
неопубликованный draft устранил Finance DB/file ambiguity, и повторный R-0I
открыл goods-return identity gate. Claims source keys в текущем окне не
обнаружены. Repeat R-0I после pagination hardening подтвердил
`paginationMismatchPresent=false`, но claims/complete gates и общий
implementation gate остались закрыты.
Source-specific accepted-решение для R-1 принято; R-2 остаётся закрыт до
собственного положительного identity evidence.

# Changelog

- 2026-07-22 — repeat live R-0I из `main@0deacf4` подтвердил полную claims
  active/archive pagination без mismatch. Доступный scope пуст, другой закрыт
  по доступу; source keys отсутствуют, поэтому claims/complete и общий gates
  закрыты. Test-only full preflight остановлен выключенным master-флагом;
  dry-run не создал report, environment не менялся.

- 2026-07-22 — claims R-0/R-0I runner hardened до полной active/archive
  pagination с provider-total reconciliation, duplicate-ID guard, bounded page
  cap, rate-limit pacing и boolean `paginationMismatchPresent`. R-2 не открыт;
  raw comments/identifiers/counts не выводятся.

- 2026-07-22 — реализован R-1 source package: registered goods-return
  collection, raw integrity, DB/file selector, strict envelope/window,
  deterministic normalization и exact Finance.srid internal link/coverage.
  Report mart/API/UI и environment rollout не выполнялись.

- 2026-07-22 — принят exact goods-return R-1 контракт
  `srid → Finance.srid` с tenant/client/cabinet/nm scope и одной canonical
  return chain. Открыт только R-1 без mart/API/UI; claims и общий F-5 gate,
  client/production rollout остаются закрыты.

- 2026-07-22 — отдельно разрешённый production full source refresh создал
  неопубликованный immutable draft с verified file-authoritative Finance без
  DB/file ambiguity; current report и feature flags не менялись. Повторный R-0I
  открыл exact goods-return `srid → Finance.srid` gate и подтвердил canonical
  return chain. Claims source keys отсутствуют, поэтому claims/complete gates и
  `implementationGate` закрыты; контракт требует отдельного accepted-изменения
  перед R-1.

- 2026-07-22 — F-5 R-0L newest-first проверил существующие immutable reports
  без внешних API и записей. Verified unambiguous return lineage не найден;
  selector повторно зафиксировал source integrity failure и DB/file ambiguity,
  поэтому `newReportRequired=true`, reuse decision отсутствует, R-1…R-5
  закрыты. Evidence не разрешает migration/runtime rollout или retention
  mutation.

- 2026-07-22 — F-5 R-0I выполнен fail closed: source schema доступна, но
  production selector обнаружил DB/file storage ambiguity выбранного Finance
  snapshot. Verified lineage и exact crosswalk не доказаны; R-1…R-5 закрыты до
  нового immutable report из однозначного verified storage. Синхронизирован
  устаревший итоговый status F-4 с завершённой staff-only test acceptance.

- 2026-07-21 — реализован F-4 package за defaults-off флагами: безопасный
  source-gate mode, read-only collectors с provider-total reconciliation,
  verified DB/file dual snapshots, deterministic event mart, additive schema,
  atomic context+rows и publication gate, `/logistics/measurements`, role/flag
  matrix и responsive UI с локальной error isolation. Staff-only test rollout
  выполняется только после merge; production/client enable не выполнялись,
  factor-spec остаётся `accepted`.

- 2026-07-21 — принят отдельный spec-first контракт F-4 «Замеры и удержания»:
  исправлен источник с общего Finance penalty на Analytics
  `measurement-penalties`/`warehouse-measurements`, определены live source gate,
  verified dual-source lineage, `wb-logistics-measurements-v1` context/event
  mart, exact cabinet/nm mapping без дублирования, money/reversal/net semantics,
  `/logistics/measurements`, состояния и incidence-aware coverage, defaults-off
  flags, synthetic responsive target и staff-only rollout boundary. Product-код
  и среды не менялись; factor-spec остаётся `accepted`.

- 2026-07-21 — принят точный контракт F-3 «Склады и маршруты»: verified
  `supplier/sales`, exact cabinet/srid/nm join, explicit missing/mixed,
  route context/mart reconciliation, `/routes`, defaults-off flags и
  staff-only visual target. Глобальный coverage threshold снят в пользу
  per-chain admissibility, чтобы частичный scope одного кабинета не скрывал
  валидный другой кабинет.

- 2026-07-21 — принят точный контракт F-2 «Тарифы»: официальный WB contract
  повторно проверен (обязательный `date`, текущие/архивные box/pallet,
  percent-поля и token-dependent rate limits), добавлены weekly collection,
  verified lineage/DB-file rules, `wb-logistics-tariffs-v1` context/mart,
  `/logistics/tariffs`, states/coverage/recommendations, отдельные defaults-off
  flags, visual target и staff-only test rollout. Общий spec остаётся
  `accepted`; реализация F-4, F-5 и client/production enable не входят.

- 2026-07-20 — F-1 «Габариты» доведён до staff-only test: добавлены flags и
  role matrix, авторитетный Content snapshot selector с DB/file parity и
  fail-closed integrity gate, нормализация карточек и dimension mart,
  атомарный immutable context+rows, полная state matrix API, coverage полного
  среза, детерминированные рекомендации и responsive UI. На test применена
  additive migration, создан новый draft из verified snapshot и выполнена
  desktop/mobile staff/client приёмка. Factor-spec остаётся `accepted`,
  production и клиентское включение не выполнялись.

- 2026-07-19 — создан draft второй очереди (`WP-5 Факторы`) по запросу
  продолжить план разработки: зафиксированы источники и их read-only границы с
  перепроверкой официальных WB API (Content `dimensions`, Statistics склад/
  направление, Tariffs box/pallet с периодами, миграция финансового отчёта на
  `sales-reports/detailed` с 15.07.2026), план probe доступности, витрины
  `report_logistics_dimension_rows`/`report_logistics_route_rows`, additive API
  `/dimensions` и `/routes`, модель факт/оценка/гипотеза/недоступно, крайние
  случаи, acceptance, rollout/rollback и открытые вопросы. Живой probe не
  выполнялся; контракты полей помечены как требующие построчной сверки по
  Swagger.
- 2026-07-19 — добавлены результаты probe по сохранённым данным test (без
  ключей): габариты подтверждены (есть во всех сохранённых карточках) и F-1
  начат — извлечение `dimensions` в плоскую карточку реализовано; склад/
  направление, тарифы и причины возвратов в сохранённых данных отсутствуют и
  требуют живого read-only probe с ключами клиента. Обновлены открытые вопросы.
- 2026-07-19 — статус изменён на `accepted` после живого read-only probe
  источников: подтверждены тарифы box/pallet с периодами, goods-return с
  `reason` и статистика склад/направление (по кабинету с полным scope).
  Реализован читающий слой: извлечение `dimensions`, коннекторы
  `wb_tariffs`/`wb_goods_return`/`wb_supplier_sales` и probe-скрипт; они внесены
  в `related_code`/`related_tests`. Проектные решения переведены в согласованные.
  Не реализованы: сохранение снимков, витрины, API и блок факторов — следующими
  подпакетами за выключенным флагом. На тот момент F-4 ошибочно был привязан к
  Finance и оставлен до сверки Swagger; решение исправлено записью 21.07.2026
  про отдельные Analytics Reports.
- 2026-07-20 — синхронизировано состояние после PR №34–39 и принят контракт
  завершения F-1 до staff-only test: отдельные factor flags, versioned dimension
  context, DB/file-authoritative selection, строгий join cabinet+nmId,
  детерминированное схлопывание, полная state matrix `/dimensions`, локальный
  factor UI и publication/rollout boundaries. Статус всего спека остаётся
  `accepted`, потому что F-2–F-5 не завершены.
