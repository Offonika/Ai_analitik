---
spec_id: "workspace-shumeyko-partners-wb-logistics-cost-factors-implementation"
title: "WB: факторы затрат на логистику (вторая очередь)"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "consultant"]
source_of_truth: false
related_code: [src/wb_unit_economics/wb_content.py, src/wb_unit_economics/wb_tariffs.py, src/wb_unit_economics/wb_goods_return.py, src/wb_unit_economics/wb_supplier_sales.py, src/wb_unit_economics/wb_stocks.py, src/wb_unit_economics/logistics_analysis.py, src/wb_unit_economics/web/source_refresh.py, src/wb_unit_economics/web/repository.py, src/wb_unit_economics/web/models.py, src/wb_unit_economics/web/database.py, src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/settings.py, src/wb_unit_economics/web/static/index.html, src/wb_unit_economics/web/static/app.js, src/wb_unit_economics/web/static/styles.css, sql/postgres_schema.sql]
related_tests: [tests/test_wb_content.py, tests/test_wb_tariffs.py, tests/test_wb_goods_return.py, tests/test_wb_supplier_sales.py, tests/test_wb_stocks.py, tests/test_logistics_analysis.py, tests/test_logistics_factor_marts.py, tests/test_db_first_publication.py, tests/test_source_refresh.py, tests/test_web_app.py]
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
    symbols: ["def build_dimension_rows"]
  - path: src/wb_unit_economics/web/source_refresh.py
    symbols: ["def _build_and_persist_logistics_dimensions", "def _select_dimension_snapshot"]
  - path: src/wb_unit_economics/web/repository.py
    symbols: ["def replace_report_logistics_dimension_analysis", "def report_logistics_dimensions_payload"]
test_anchors:
  - path: tests/test_logistics_analysis.py
    symbols: ["def test_build_dimension_rows_links_by_nm_and_marks_unavailable"]
  - path: tests/test_web_app.py
    symbols: ["def test_logistics_dimensions_api_partial_coverage_uses_full_filtered_slice", "def test_logistics_dimensions_role_and_flag_matrix"]
  - path: tests/test_source_refresh.py
    symbols: ["def test_dimension_snapshot_db_and_file_authoritative_are_equivalent", "def test_dimension_snapshot_integrity_failures_are_blocking"]
depends_on: [workspace-shumeyko-partners-wb-logistics-cost-analysis-implementation]
rollout_required: true
updated_at: "2026-07-20"
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
статистика склад/направление (по кабинету с полным scope). Построчная сверка
Swagger по фактическим полям нового финансового метода остаётся открытым
пунктом и не блокирует принятый дизайн.

# Текущее состояние реализации

Первая очередь (`wb-logistics-v5`, фактический MVP) реализована; см. канонический
спек и
[`docs/runbooks/wb-logistics-v4-continuation.md`](../runbooks/wb-logistics-v4-continuation.md).

Реализованный читающий слой второй очереди:

- `src/wb_unit_economics/wb_content.py` — извлечение `dimensions` (габариты, вес,
  `isValid`) из карточек (F-1);
- `src/wb_unit_economics/wb_tariffs.py` — read-only тарифы box/pallet с периодами
  действия (F-2);
- `src/wb_unit_economics/wb_goods_return.py` — read-only причины возврата
  продавцу (goods-return);
- `src/wb_unit_economics/wb_supplier_sales.py` — read-only склад отгрузки и
  направление доставки (F-3);
- `scripts/probe_wb_logistics_factors.py` — read-only probe доступности.

После PR №34–39 в `main` появились additive schema для dimension/route mart,
чистая сборка dimension rows, snapshot exporters факторов, optional collectors,
repository persistence и первичный read-only API `/dimensions`.

F-1 «Габариты» собран сквозным пакетом и принят на staff-only test 20 июля
2026 года: штатный report build выбирает и повторно проверяет авторитетный
snapshot карточек, атомарно сохраняет dimension context/mart, API реализует
state matrix, фильтры, SQL-pagination и coverage полного среза, а factor-блок
встроен в `#tables/logistics`. Operational evidence находится в
[`docs/runbooks/wb-logistics-v4-continuation.md`](../runbooks/wb-logistics-v4-continuation.md).
Статус всего factor-spec остаётся `accepted`: сохранение и расчёт тарифов,
возвратов и продаж, route mart, `/routes`, фактические замеры/штрафы, factor AI
digest и клиентский/production rollout остаются следующими подпакетами.

# Цель

Дать пользователю подтверждённые факторы, связанные с высокой стоимостью
логистики, не превращая гипотезы в факты. Ответить на третий вопрос сценария
(«какие подтверждённые факторы связаны с высокой стоимостью») из канонического
спека, оставаясь read-only и сохраняя явные статусы `Факт`, `Оценка`,
`Гипотеза` и `Данные недоступны`.

Вторая очередь добавляет к готовому фактическому блоку:

1. заявленные габариты и вес товара с упаковкой и сигнал расхождения карточки;
2. подтверждённые фактические замеры/штрафы WB там, где источник их содержит;
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
- `Фактический замер / штраф` — измеренные WB габариты и денежное списание,
  подтверждённые финансовым отчётом реализации. Это `Факт`.
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
- сбор подтверждённых фактических замеров/штрафов из финансового отчёта
  реализации, если probe подтвердит наличие полей;
- витрины `report_logistics_dimension_rows` и `report_logistics_route_rows`;
- read-only API `/logistics/dimensions` и `/logistics/routes`;
- блок факторов на первом экране логистики с явными статусами основания;
- детерминированные рекомендации по расхождению габаритов и дорогому
  направлению.

## Out Of Scope

Наследует Out Of Scope канонического спека. Дополнительно вне scope:

- любые write-методы WB, включая ответы покупателю `POST returns/claim` и
  обновление карточек товара;
- калькуляторы логистики и маржинального дохода (третья очередь);
- трактовка `isValid=false` как штрафа или доказанного расхождения;
- применение текущего тарифа к историческому периоду как факта;
- автоматическое изменение распределения товара по складам;
- Ozon и другие маркетплейсы.

# Источники и границы чтения

Все методы ниже read-only и вызываются токенами минимально необходимых
категорий (least privilege). Точные имена полей и путей взяты из официальных
страниц WB, но НЕ сверены построчно по Swagger; поля с пометкой
`требует подтверждения` фиксируются контрактом только после probe.

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
- Историческая дата запрашивается query-параметром `date` (`YYYY-MM-DD`) —
  имя/обязательность и самая ранняя доступная дата архива `требует
  подтверждения`.
- `GET https://common-api.wildberries.ru/api/tariffs/v1/acceptance/coefficients`
  — коэффициенты приёмки по складам.
- Rate limit 60 запросов/мин; поле `dtFromMin` удалено WB 15.07.2026 — в
  парсер не закладывать.

## Фактические замеры и штрафы — Finance report

- С 15.07.2026 отчёт реализации мигрирован:
  `GET /api/v5/supplier/reportDetailByPeriod` отключён; замена —
  `POST https://.../api/finance/v1/sales-reports/detailed/{reportId}`
  (токен «Финансы», поля camelCase, денежные значения строками, набор полей
  настраивается массивом `fields`).
- Целевые поля: фактические (замеренные) габариты, `penalty`,
  `bonus_type_name`/аналог, `warehouseName` — все `требует подтверждения` по
  Swagger finances. Отдельной строки «штраф именно за габариты» в документации
  не подтверждено.
- Отчёт платного хранения `GET /api/v1/paid_storage` (задание → опрос статуса →
  выгрузка): `volume`, коэффициент склада, `warehousePrice`; окно ~8 дней за
  запрос.

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
2. Finance (новый метод): присутствуют ли фактические габариты, `penalty` и
   `warehouseName` в реальном отчёте; сверить состав полей по Swagger.
3. Tariffs: доступен ли архив за нужные исторические недели; какая самая ранняя
   дата отдаётся; совпадает ли `warehouseName` тарифа со складом продаж.
4. Statistics: покрытие `warehouseName` и направления за период отчёта; глубина
   90 дней достаточна для выбранных отчётов?
5. Join: связуемость `nmId`/`srid`/`warehouseName` между продажами, тарифами,
   карточками и финансовым фактом без дублирования сумм.
6. Замеры/штрафы: подтверждается ли хотя бы один сквозной пример
   «расхождение → коэффициент недели → денежное списание» на реальных данных.

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
| Замеры/штрафы (Finance new) | ⚠️ не проверено | Требует живого вызова нового метода `sales-reports/detailed`. |

Следствие для порядка подпакетов: **F-1 (габариты)** разблокирован на уровне
источника и начат — извлечение `dimensions` в плоскую карточку реализовано
(read-only, `None` без подстановки нуля). F-3 (склад/маршруты), F-2 (тарифы) и
причины возвратов требуют живого read-only probe с ключами клиента до
реализации.

# Расчётная модель факторов

Модель наследует правила первой очереди и добавляет факторный слой без
изменения фактической суммы логистики и её классификации.

- Заявленные габариты и вес показываются как введённые продавцом значения.
  `isValid=false` показывается как `Сигнал`, а не факт замера.
- Фактический замер/штраф показывается как `Факт` только при подтверждённом
  финансовом источнике; сумма штрафа не смешивается с базовой логистикой.
- Коэффициент недели связывается с календарной неделей операции. Для
  исторической недели применяется коэффициент того же периода; при отсутствии
  архива вывод помечается `Оценка` и историю им не объясняют.
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

## `report_logistics_route_rows`

Уже зарезервирована каноническим спеком. Гранулярность — склад и доступное
направление доставки. Создаётся только при достаточном покрытии исходных полей
(порог покрытия фиксируется по результату probe). Поля: склад, направление,
фактическая логистика среза, число цепочек, `low_sample`, коэффициент недели
при наличии, `evidenceType`, source hash.

# API

Additive read-only методы, зарезервированные каноническим спеком; переиспользуют
авторизацию, tenant boundary, роли, пагинацию и фильтры кабинета:

- `GET /api/reports/{report_id}/logistics/dimensions` — вторая очередь;
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

# Интерфейс

Блок факторов встраивается в существующий answer-first экран логистики
(`#tables/logistics`) как второй уровень, не создавая отдельного пункта меню и
не меняя денежный итог первого экрана.

- Показывает габариты/вес, сигнал расхождения, подтверждённые замеры/штрафы,
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

# Правила рекомендаций

Наследуют формат первой очереди (`code`, `priority`, `title`, `message`,
nullable `impactAmount`, `evidenceType`, `actionTarget`, `actionLabel`,
`evidence`; сортировка по priority, затем по убыванию `|impactAmount|`).
Добавляются флаги:

- подтверждённое расхождение габаритов → проверить упаковку и данные карточки
  (`evidenceType=fact` только при подтверждённом замере, иначе `limitation`);
- высокий расход на конкретном направлении → проверить распределение запасов;
- `isValid=false` без финансового подтверждения → пометка ограничения, не факт.

Лидеры выбираются SQL по полному фильтрованному срезу, не из top-10 общего
рейтинга.

# AI Boundary

Наследует канонический AI Boundary. AI получает только рассчитанные факторные
витрины и разрешённые evidence-поля; не читает raw payload, не придумывает
причину возврата, не объявляет товар убыточным по одному фактору или
коэффициенту, не подставляет отсутствующее значение нулём. AI обязан разделять
`Факт`, `Оценка`, `Гипотеза` и `Данные недоступны`.

# Ошибки и пограничные случаи

- Нет `dimensions` в карточке → фактор габаритов `data_unavailable`, gate не
  блокируется.
- `isValid=false` без финансового факта → только сигнал, не штраф.
- Нет исторического тарифа за нужную неделю → коэффициент показывается как
  `Оценка` по явно выбранному тарифу, историю им не объясняют.
- Нет направления доставки → маршрутная витрина не строится (правило канона).
- Несколько складов/направлений в одной цепочке → `mixed`, а не первое
  значение.
- Разные rate limits источников → backoff на 429, частичный сбор помечается
  `partial`, а не тихо обрезается.
- Смена финансового отчёта (15.07.2026): чтение только нового метода
  `sales-reports/detailed`; старый v5-эндпоинт не используется.
- Новая обязательная витрина со статусом `blocked`/устаревшей методикой →
  publication blocker, как в первой очереди.
- DB/file ambiguity, изменившийся manifest/hash/row count, выход raw path за
  разрешённый root, foreign tenant/client/cabinet и две разные ревизии Content
  одинакового lineage-приоритета → `blocked`; dimension rows не сохраняются.
- Для Content выбирается один полный snapshot по приоритету
  `primary -> base -> contributor`. Частичный snapshot не дополняется старыми
  строками другой ревизии: доступные товары показываются, остальные получают
  `data_unavailable`.

# Безопасность и tenant isolation

- Каждый запрос ограничен tenant/client/cabinet доступами пользователя.
- Внешние интеграции остаются read-only; write-методы (ответ покупателю,
  обновление карточек) запрещены.
- Raw payload, токены и секреты не возвращаются интерфейсу и AI.
- Действующие audit, session, retention и backup правила применяются без
  ослабления.

# Этапы реализации

Соответствует `WP-5 Факторы` канонического спека и разбивается на подпакеты:

1. `F-0 Probe доступности` — обезличенная матрица доступности источников на
   реальном снимке; определяет включаемый состав.
2. `F-1 Габариты` — извлечение `dimensions` из карточек, витрина
   `report_logistics_dimension_rows`, API `/dimensions`, блок UI.
3. `F-2 Тарифы и коэффициенты` — коннектор box/pallet с периодами действия,
   привязка коэффициента недели.
4. `F-3 Склады и маршруты` — направление/склад из продаж, витрина
   `report_logistics_route_rows`, API `/routes`, агрегаты.
5. `F-4 Замеры и штрафы` — только при подтверждении probe: фактические габариты
   и штрафы из финансового отчёта.
6. `F-5 Приёмка и rollout` — staff-only проверка за флагом, затем отдельное
   решение о клиентском включении.

Каждый подпакет реализуется за выключенным флагом и additive-миграцией схемы;
последовательность после F-0 уточняется матрицей доступности.

# Acceptance Criteria

Design-часть draft считается принятой, когда владелец подтвердил состав MVP
факторов и разделение факт/оценка/гипотеза/недоступно. Реализация второй
очереди считается готовой, когда:

1. probe зафиксировал доступность каждого источника обезличенной матрицей, и
   недоступные факторы явно помечены `data_unavailable`, а не заполнены нулём;
2. заявленные габариты и `isValid` показаны как значение продавца/сигнал, а не
   как факт замера WB;
3. фактический замер/штраф показан как `Факт` только при подтверждённом
   финансовом источнике и не смешан с базовой логистикой;
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

# Test Plan

- unit: извлечение `dimensions`/`weightBrutto`/`isValid` из карточки, включая
  отсутствующий объект и `isValid=false`;
- unit: привязка коэффициента недели к периоду; отсутствие архива → `Оценка`;
- unit: агрегация склад/направление, `mixed` при конфликте;
- unit: `evidenceType` факторов и запрет нулевой подстановки;
- integration: сборка витрин `report_logistics_dimension_rows` и
  `report_logistics_route_rows` из обезличенного снимка, lineage и hash;
- API: `/dimensions` и `/routes` возвращают статусы, покрытие и факт/оценку;
  пустой срез → `empty`; старый отчёт → `needs_rebuild`;
- tenant isolation: недоступность чужих tenant/cabinet во всех новых методах;
- fixtures обезличенные; реальные идентификаторы и клиентские объёмы в тесты и
  документацию не переносятся.
- source integration: DB/file parity, lineage precedence, raw integrity/path,
  storage ambiguity и tenant scope;
- browser: staff-only deep-link на desktop/mobile, client 404/скрытый блок,
  отсутствие overflow и console/page/network errors.

Файлы (расширяются существующие): `tests/test_wb_content.py`,
`tests/test_wb_stocks.py`, `tests/test_logistics_analysis.py`,
`tests/test_source_refresh.py`, `tests/test_web_app.py`; новые тесты тарифного
коннектора добавляются вместе с ним.

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

Rollback отключает новые API-маршруты и факторный блок, не изменяя существующие
отчёты и первую очередь. Новые витрины additive и неизменяемы. Внешние источники
при rollout и rollback не изменяются. Отключение флага не снимает publication
blocker с report run, который обязан был пройти gate, но не прошёл.

# Согласованные решения

Решения приняты после живого probe (2026-07-19):

1. Заявленные габариты и `isValid` — это значение продавца и сигнал; фактом
   замера считается только подтверждённый финансовый источник.
2. Исторический тариф/коэффициент берётся по периоду; текущий — только
   `Оценка`.
3. Финансовый отчёт читается новым методом `sales-reports/detailed`; старый
   `reportDetailByPeriod` не используется.
4. Витрины factors additive и неизменяемы; отсутствие фактора не заполняется
   нулём.
5. Блок факторов встраивается в существующий экран логистики, без отдельного
   пункта меню.
6. Калькуляторы остаются третьей очередью и в этот draft не входят.

# Открытые вопросы

- Точный состав полей нового финансового метода (фактические габариты,
  `penalty`, `warehouseName`) — сверить по Swagger finances (требует live).
- Имя/обязательность параметра `date` тарифов и глубина архива для
  исторического пересчёта (требует live).
- Порог покрытия, при котором строится `report_logistics_route_rows`.
- Нужно ли начать сохранять Statistics `supplier/sales` (склад/направление):
  сейчас этих полей в сохранённом снимке нет — probe подтвердил.
- Нужен ли отдельный retention для тарифного snapshot (тарифы общие, не
  клиентские).
- Разрешение на живой read-only probe тарифов/statistics/возвратов через
  приложение с ключами клиента (на test).

Частично закрытые probe (2026-07-19): габариты — источник подтверждён и F-1
начат; минимальный состав первой поставки — начинать с F-1 (габариты), так как
данные уже есть, остальные подпакеты после живого probe.

# Changelog

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
  подпакетами за выключенным флагом. F-4 (финансовые замеры/штрафы) — после
  построчной сверки Swagger.
- 2026-07-20 — синхронизировано состояние после PR №34–39 и принят контракт
  завершения F-1 до staff-only test: отдельные factor flags, versioned dimension
  context, DB/file-authoritative selection, строгий join cabinet+nmId,
  детерминированное схлопывание, полная state matrix `/dimensions`, локальный
  factor UI и publication/rollout boundaries. Статус всего спека остаётся
  `accepted`, потому что F-2–F-5 не завершены.
