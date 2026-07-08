---
spec_id: "marketplace-unit-economics-ozon-integration"
title: "Marketplace unit economics: Ozon integration"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
source_of_truth: true
related_code: [src/wb_unit_economics/ozon.py, src/wb_unit_economics/ozon_mart.py, src/wb_unit_economics/marketplace.py, src/wb_unit_economics/contracts.py, src/wb_unit_economics/web/source_refresh.py, src/wb_unit_economics/web/providers.py, src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/static/app.js]
related_tests: [tests/test_ozon.py, tests/test_ozon_mart.py, tests/test_contracts.py, tests/test_provider_registry.py, tests/test_source_refresh.py, tests/test_web_app.py]
contracts: [ozon_api_snapshot, ozon_product_snapshot, ozon_stock_snapshot, ozon_sku_mapping, marketplace_api_snapshot, unit_economics_report]
depends_on: [docs/specs/wb-unit-economics-excel-mvp-implementation.md, docs/specs/wb-unit-economics-db-first-report-marts.md, docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md]
supersedes: []
rollout_required: true
updated_at: "2026-07-07"
---

# Goal

Добавить Ozon как второй read-only маркетплейс в финмодель WB/1C без
регрессии существующего WB-контура.

V1 не заменяет WB-методику. V1 добавляет provider `ozon_api`, raw snapshots
Ozon и общий контракт `marketplace_api_snapshot`, где `marketplace` принимает
значения `wb` или `ozon`. Для клиентов без WB допускается диагностический
режим `ozon-only`: он читает Ozon + 1C и сохраняет source snapshots, но не
публикует unit economics отчет до mart validation и отдельной приемки
нормализации Ozon. Смешанный отчет WB+Ozon можно публиковать только после той
же приемки.

# Scope

Входит:

- read-only provider `ozon_api` в registry web-кабинета;
- авторизация Ozon через `Client-Id` и `Api-Key`;
- source collectors для Ozon finance cash-flow, realization, products, stocks
  и returns;
- staff-only блок `Диагностика Ozon + 1C` в web-кабинете для статусов
  последних Ozon/1C source collections без публикации смешанной прибыли;
- staff-only endpoint `GET /api/clients/{client_id}/ozon-diagnostics`, который
  показывает безопасную диагностику последнего `ozon-only` запуска;
- source refresh mode `ozon-only` для клиентов без WB: Ozon realization,
  Ozon catalog/mapping и 1C OData без обязательного WB Finance;
- сохранение raw Ozon JSON snapshots в `data/source_refresh/...`;
- manifest с endpoint, account, hash, row count, status, report code и errors;
- новые контракты `ozon_api_snapshot`, `ozon_product_snapshot`,
  `ozon_stock_snapshot`, `ozon_sku_mapping`, `marketplace_api_snapshot`;
- нормализация WB и Ozon в общий `MarketplaceApiSnapshot`;
- явные quality statuses для `missing_mapping`, `ambiguous_mapping`,
  `missing_cost`, `partial_source`.

Не входит:

- запись в Ozon, WB, 1С, банк, CRM, почту или уведомления;
- автоматическая публикация смешанного WB+Ozon отчета без проверки Ozon marts;
- подстановка нулевой себестоимости при отсутствии маппинга или стоимости;
- хранение секретов, raw data или отчетов в Git/Markdown.

# Ozon API Sources

Перед реализацией и перед каждым production rollout инженер обязан повторно
открыть официальную документацию Seller API и changelog Ozon.

Зафиксированные V1 endpoints:

| Назначение | Endpoint | Режим | Комментарий |
| --- | --- | --- | --- |
| Проверка ключа | `POST /v1/finance/cash-flow-statement/list`, затем `POST /v2/analytics/stock_on_warehouses` | live read-only check | Проверка считается успешной, если проходит хотя бы один реально используемый read-only source endpoint. |
| Финансы и деньги | `POST /v1/finance/cash-flow-statement/list` | daily/weekly/full | Используется вместо `transaction/list`; `details` сохраняются как денежный cash-flow контроль, но не являются P&L базой прямых расходов. |
| Взаиморасчеты | `POST /v1/finance/mutual-settlement` + `POST /v1/report/info` | weekly/full/ozon-only | Помесячный read-only отчет по `date = YYYY-MM`; основной Ozon API источник документных прямых расходов и сверки с 1C услугами. |
| Реализация | `POST /v2/finance/realization` | weekly/full | Помесячный отчет, request body `month` + `year`; требует сверки полей перед расчетом. |
| Позаказная реализация | `POST /v1/finance/realization/posting` | weekly/full/ozon-only | Вспомогательный отчет для сверки заказов; request body `month`, `year`, `page`; не заменяет закрывающий отчет реализации. |
| Выкупы | `POST /v1/finance/products/buyout` | weekly/full/ozon-only | Дополнительный источник для объяснения расхождений с 1C расходными накладными; request body `date_from` + `date_to` в формате `YYYY-MM-DD`, период режется на месячные чанки из-за лимита 31 день. |
| B2B продажи | `POST /v1/finance/document-b2b-sales/json` | weekly/full/ozon-only | Дополнительный источник для продаж юрлицам; используется только как сверка. Request body `date` в формате `YYYY-MM`; строки считаются по верхнему массиву `invoices`. |
| Товары | `POST /v1/report/products/create` + `POST /v1/report/info` | weekly/full | Асинхронный отчет, V1 хранит raw JSON с code/status/file metadata. |
| Остатки | `POST /v2/analytics/stock_on_warehouses` | weekly/full | Пагинация `limit/offset`. |
| Возвраты | `POST /v2/report/returns/create` + `POST /v1/report/info` | weekly/full | Асинхронный отчет по возвратам. |

Источник по отключению старых финансовых методов:
[Ozon Seller API notification](https://t.me/s/OzonSellerAPI?before=663) и
[dev.ozon.ru news](https://dev.ozon.ru/news/699-Novye-metody-dlia-finansovykh-otchetov-v-Seller-API/)
сообщают, что 6 июля 2026 года методы
`/v3/finance/transaction/list` и `/v3/finance/transaction/totals` отключаются.
Поэтому V1 не строится на этих методах.

# Provider Registry

Provider `ozon_api`:

- label: `Ozon Seller API`;
- read-only: `true`;
- default role: `finance_reports`;
- roles:
  - `finance_reports`;
  - `products_catalog`;
  - `stocks_analytics`;
  - `returns_reports`;
  - `full_readonly`;
- supports multiple connections: `true`.

Секрет хранится только в `.env` или encrypted `tenant_integrations`.
Допустимые форматы:

- JSON object: `{"clientId":"...","apiKey":"..."}`;
- JSON object with accounts: `{"accounts":[...]}`;
- key-value string: `clientId=...;apiKey=...`.

Секреты не выводятся в API payload, logs, Markdown, Git или validation errors.

# Source Refresh

План collectors:

| Mode | Collectors |
| --- | --- |
| `daily` | mapping, WB finance, Ozon finance cash-flow, 1C OData |
| `weekly` | mapping, WB finance, WB report list, Ozon finance, Ozon mutual settlement, Ozon realization, Ozon posting realization, Ozon buyouts, Ozon B2B sales, Ozon products, Ozon stocks, Ozon returns, 1C OData |
| `full` | same as `weekly` |
| `onec-only` | mapping, 1C OData |
| `ozon-only` | mapping, Ozon finance cash-flow, Ozon mutual settlement, Ozon realization, Ozon posting realization, Ozon buyouts, Ozon B2B sales, Ozon products, 1C OData |

Ozon collectors optional. Если Ozon не подключен, существующий WB/1C refresh не
должен менять поведение. Если Ozon подключен, но отдельный Ozon collector упал,
run получает `needs_review` или `partial_source`, а не нулевые показатели.
В режиме `ozon-only` WB credentials не требуются. Для диагностической витрины
обязательны Ozon realization, mapping и обязательные 1C коллекции. Ozon
finance cash-flow может сохраняться как технический raw source для будущей
финансовой сверки, но не является источником выручки, не является обязательным
для Ozon v1 и не отображается в расчетной витрине.
Для `POST /v2/finance/realization` ответ 404 `Report was not found` по текущему
незакрытому месяцу считается `empty_expected`; закрытые загруженные месяцы все
равно участвуют в диагностике. Проверка себестоимости может быть ограничена
безопасным лимитом строк и должна показывать, сколько realization-строк
использовано из общего числа загруженных.
Завершение режима не создает и не публикует отчет.

Диагностическая витрина `ozon-only`:

- доступна только staff-пользователям через
  `GET /api/clients/{client_id}/ozon-diagnostics`;
- берет последний `source_refresh_runs` с `mode = ozon-only` для выбранного
  клиента;
- поддерживает безопасные query-фильтры `period_start`, `period_end` и
  `wb_cabinet_id`, чтобы показатели Ozon пересчитывались под выбранный период и
  Ozon-кабинет;
- возвращает только safe metadata: статус запуска, период, счетчики коллекций,
  readiness по Ozon realization, mapping и обязательным 1C источникам;
- не возвращает и не отображает preview Ozon cash-flow как расчетную выручку;
- не возвращает raw payload целиком, raw paths, hashes, `Client-Id`, `Api-Key`
  или вложенные необработанные объекты.

Raw snapshots сохраняются под `data/source_refresh/<snapshot_set>/ozon_*`.
Каждый collector пишет `manifest.json` с:

- `source`;
- `sourceEndpoint`;
- `loadedAt`;
- `sellerAccountId`;
- `pageIndex`;
- `status`;
- `rowCount`;
- `statusCode`;
- `rawPayloadHash`;
- `outputFile`;
- `reportCode`;
- `error`.

# Data Contracts

`ozon_api_snapshot` содержит финансовую строку Ozon:

- `client_id`, `seller_account_id`, `organization_id`;
- `period_start`, `period_end`, `loaded_at`;
- `source_endpoint`, `source_report_code`, `raw_payload_hash`;
- `product_id`, `ozon_sku`, `offer_id`, `vendor_code`, `barcode`;
- `sales_quantity`, `return_quantity`, `quantity`;
- `gross_revenue`, `net_revenue`, `commission`, `logistics`, `storage`,
  `promotion`, `penalties_and_holdbacks`, `acquiring`, `payout`;
- `currency`, `is_partial_source`.

`ozon_product_snapshot` содержит product/catalog facts: `product_id`,
`ozon_sku`, FBO/FBS SKU, `offer_id`, `vendor_code`, `barcode`, price/status и
`raw_payload_hash`.

`ozon_stock_snapshot` содержит stock facts по складу: `product_id`,
`ozon_sku`, `offer_id`, `warehouse_id`, `warehouse_name`, `stock_type`,
`present`, `reserved`, in-way quantities и `raw_payload_hash`.

`ozon_sku_mapping` связывает кандидаты Ozon (`offer_id`, `product_id`, `sku`,
barcode, product name) с 1С. Основной источник соответствия - загруженный
read-only файл сопоставления `Номенклатура Ozon` -> `Номенклатура` и 1С
marketplace mapping. Статусы: `matched`, `missing`, `ambiguous`, `excluded`.

`marketplace_api_snapshot` является общим расчетным контрактом:

- `marketplace = wb|ozon`;
- `seller_account_id`, `organization_id`;
- `product_id`, `nm_id`, `ozon_sku`, `offer_id`, `vendor_code`, `barcode`;
- sales/return quantities;
- revenue, commission, logistics, storage, acceptance/placement, promotion,
  penalties/holdbacks, acquiring, payout;
- `raw_payload_hash`, `source_endpoint`, `loaded_at`, `is_partial_source`.

# Web Preview

Первый web-шаг Ozon — отдельный staff-only блок `Диагностика Ozon + 1C` на
основном экране выбранного клиента. Он должен быть виден даже когда у клиента
нет опубликованного WB-отчета. Блок не является клиентской витриной прибыли и
не смешивает Ozon с WB. Он показывает только безопасные агрегаты последнего
`ozon-only` source refresh:

- верхний фильтр кабинета должен быть универсальным для marketplace-кабинетов
  (`Кабинет МП`) и включать WB и Ozon подключения выбранного клиента;
- если выбран конкретный WB-кабинет, Ozon-блок скрывается;
- если выбран Ozon-кабинет или все кабинеты клиента с Ozon-подключением,
  Ozon-блок показывает диагностику;
- список Ozon, mapping и обязательных 1C source collections;
- отдельный блок `Сопоставление Ozon → 1C`, который использует
  `ozon_products_report`/catalog rows, а не cash-flow aggregate;
- счетчики `matched`, `missing`, `ambiguous`, `no_key` и bounded preview строк
  сопоставления;
- `loaded`, `empty_expected`, `needs_review`, `auth_failed` и другие статусы;
- row count;
- source endpoint;
- report code для асинхронных отчетов, если он есть;
- безопасный комментарий по ограничению или ошибке.

В этом же блоке должна быть расчетная витрина `Ozon v1`. Методическая выручка
Ozon берется из регистра продаж 1C по контрагенту Ozon
(`ООО Интернет Решения`). Отчет комиссионера
`Document_ОтчетКомиссионера` показывается как сверка: сумма реализации из
табличной части `Запасы`, сумма возвратов из `ЗапасыВозвраты`, net sales, НДС,
количество строк и разница к регистру продаж. Если регистр продаж 1C содержит
дополнительные документы по тому же контрагенту, например
`Document_РасходнаяНакладная`, они входят в выручку Ozon v1 и отдельно
объясняются через дельту к отчету комиссионера. Ozon finance cash-flow не
считается бухгалтерской выручкой 1C, не участвует в P&L и не отображается в
расчетной витрине.
Если в выбранном периоде нет 1C-регистра продаж по Ozon-контрагенту, витрина
показывает пустую 1C-выручку, а не подставляет Ozon cash-flow. Если
realization-строки есть и по ним найдено сопоставление и стоимость в 1С sales
register, витрина может показать `onecCogs` и `profitAfterCogs` как
предварительный расчет.
Если связи или стоимости нет, значения `onecCogs` и `profitAfterCogs` остаются
`null`, а не превращаются в ноль.
Если регистр продаж 1C больше отчета комиссионера, диагностика должна показать
дельту и статусы дополнительных Ozon-источников:
`ozon_realization_posting`, `ozon_products_buyout`, `ozon_b2b_sales_json`.
Они объясняют возможные отдельные документы Ozon, но не меняют методическую
выручку: база выручки Ozon v1 остается `onec_sales_register`.
В Ozon v1 витрине должна быть отдельная сверка выручки:
`Ozon realization / отчет комиссионера + Ozon buyout = 1C регистр продаж`.
Если эта формула сходится, дельта Ozon vs 1C показывается как `0`, даже если
buyout подтвержден не по номеру отчета, а по контрольному агрегату.
Для отдельных выкупов Ozon ключ сверки - не номер B2B УПД, а номер отчета о
выкупленных товарах Ozon, например `4767782`. В 1C этот номер извлекается из
`Комментарий`/`ОснованиеПечати` расходной накладной с основанием `Выкуп`;
из того же комментария извлекается период отчета. Диагностика должна показывать
отдельный блок `Выкупы Ozon`: номер отчета, период, сумму и количество по 1C
расходной накладной, а также статус `found`/`not_found` относительно
загруженного `ozon_products_buyout`. Если Ozon API не возвращает номер
выкупного отчета, но месячный агрегат `ozon_products_buyout` сходится с 1C
выкупами за тот же месяц по количеству и сумме, диагностика показывает статус
`matched_by_period_total`: это объясняет дельту Ozon vs 1C, но не подменяет
номерную документную сверку. Такой случай должен попадать в review-блок как
ограничение сверки: сумма и количество подтверждены Ozon, но номер выкупного
отчета API не вернул. Даже если B2B УПД и выкупы дают похожие суммы, они не
прибавляются к выручке без сверки по номеру отчета/документа или контрольному
агрегату period+quantity+amount.
Для источника `ozon_products_buyout` счетчики должны показывать не только число
сырых API-чанков, но и количество товарных строк, сумму и количество товаров.
Старые снапшоты, где metadata `row_count` равен нулю, должны пересчитываться
для витрины из сохраненного массива `products`.
Позаказная реализация в V1 собирается с безопасным лимитом первых страниц на
месяц, а повторяющиеся страницы с тем же payload не сохраняются, чтобы
диагностика подтверждала доступность источника и не блокировала основной
`Ozon + 1C` refresh большим постраничным экспортом.
При выборе периода в веб-кабинете Ozon v1 P&L должен фильтровать документы и
строки регистра продаж 1C по дате документа/периоду. Фильтр не должен брать
выручку из Ozon cash-flow.

Витрина ошибок Ozon должна быть похожа по смыслу на WB-блок
`Что разобрать первым`: показывать статус витрины, счетчики проблем и карточки
`Ozon реализации`, `mapping`, `1C`, `missing`, `ambiguous`, `no_key`. Эти
карточки не исправляют данные автоматически. Бухгалтерия исправляет `missing` и
`ambiguous` в read-only файле сопоставления, после чего консультант повторяет
`Ozon + 1C` refresh. Если критичных проблем нет, блок показывает спокойный
статус и не блокирует чтение диагностической витрины.

# Ozon Unit Economics Mart v1

Mart v1 - отдельный staff-only расчетный слой поверх последнего `ozon-only`
source refresh. Он возвращается только в
`GET /api/clients/{client_id}/ozon-diagnostics` как блок `ozonMart` и не
создает `ReportRun`, не публикуется клиенту как WB-отчет, не попадает в Excel и
не смешивается с WB. До отдельной приемки Ozon normalization этот слой является
рабочей диагностикой консультанта/аналитика.

Источники mart v1:

- Ozon realization item rows - товарные ключи Ozon, количество и SKU-level
  комиссии/услуги;
- Ozon mutual settlement report - помесячные статьи взаиморасчетов Ozon для
  P&L прямых расходов, сверки с 1C услугами и подготовки таблицы факта;
- 1C `ИС_Маркетплейс 3.5.57.0` read-only mapping - приоритетная связь
  Ozon -> 1C из `ИС_Ozon_СоответствиеХарактеристик` и
  `ИС_Ozon_Номенклатура`, полученная через узкий HTTP-сервис `offonika`;
- 1C `Document_ОтчетКомиссионера` табличные части `Запасы` и
  `ЗапасыВозвраты` - SKU-выручка закрытых месяцев;
- 1C sales register - индекс себестоимости и контрольная 1C-выручка;
- Ozon cash-flow `details` - денежный контроль за период; отрицательные totals
  в расходных категориях показываются справочно, но не заменяют документные
  расходы mutual settlement в P&L. Положительный `details.delivery.total` не
  уменьшает расходы V1;
- 1C `Document_ПриходнаяНакладная` и, если доступно,
  `Document_ПоступлениеТоваровУслуг_Услуги` - контроль разнесения расходов
  Ozon в 1C, не главный источник расходов V1;
- Ozon buyout reconciliation - отдельная сверка, не часть SKU profit;
- Ozon mapping diagnostics - статус связи Ozon -> 1C.

Контракт `ozonMart`:

- `status`, `summary`, `totals`, `rows`, `issues`, `previewLimit`,
  `previewLimited`;
- `articleRows` - Finmodel-compatible P&L breakdown by article. The first
  release keeps the same calculation basis as mart v1, but exposes the result
  as readable rows: 1C revenue, Ozon commission, Ozon services, partner/rebilled
  services, logistics, storage, promotion/other/compensations when available,
  1C COGS and pre-tax profit;
- row fields: `periodStart`, `periodEnd`, `offerId`, `productId`, `sku`,
  `barcode`, `productName`, `onecItemId`, `onecName`, `quantity`,
  `onecRevenue`, `unitCost`, `cogs`, `ozonCommission`, `ozonServices`,
  `ozonPartnerServices`, `ozonLogistics`, `ozonStorage`, `ozonOtherExpenses`,
  `profit`, `margin`, `qualityStatus`, `expenseStatus`, `problemReason`,
  `actionText`;
- row field `expenseArticles` mirrors the article breakdown on each SKU row and
  is safe for UI/pivot rendering without raw Ozon payload.
- `articleDrilldown` connects P&L articles with source labels and SKU
  allocations. Only rows with `includedInSkuProfit=true` are distributed into
  SKU profit. Reconciliation-only rows are visible controls and must not be
  added as extra SKU expenses.

Расчетные правила:

- для закрытых месяцев март-май SKU-выручка берется только из 1C отчета
  комиссионера, если mapping однозначный и одна 1C номенклатура связана ровно
  с одним Ozon offer/SKU в mart;
- если одна 1C номенклатура соответствует нескольким Ozon offer/SKU, 1C-выручка
  не распределяется, COGS/profit не считаются, строки получают
  `ambiguous_mapping`;
- COGS считается по 1C cost index только для однозначно сопоставленных строк;
- расходы Ozon за период берутся из Ozon API mutual settlement по документным
  строкам `Акт выполненных работ`, `Отчет о перевыставлении услуг`,
  `Отчет о реализации`; 1C используется для контроля полноты разнесения;
- cash-flow `services`, `return`, `rfbs`, `others`, `delivery` показывается
  справочно как денежный контроль. Если cash-flow не сходится с mutual
  settlement за тот же месяц, витрина должна показывать это как вопрос сверки,
  а не распределять cash-flow расход по SKU;
- витрина показывает детализацию сверки расходов по статьям: категории и
  крупные операции Ozon API, операции 1C-контроля и итоговую дельту `1C -
  Ozon API`;
- по примеру `data/Finmodel.xlsm` / Finmodel 2.0 Ozon mart exposes a
  calculation article layer similar to `OzonReportTable`,
  `ServiceChargesTable`, and `tbl_OzonEconomics`: commission, services,
  partner/rebilled services, logistics, storage, promotion/other,
  compensations, COGS and profit. This is a presentation and reconciliation
  layer over the accepted source basis; it must not silently switch profit
  calculations to raw nested Ozon realization totals;
- partner/rebilled services are exposed separately as `ozonPartnerServices` and
  `partner_services`, not hidden inside generic Ozon services;
- 1C услуги Ozon без пары в API за выбранный месяц показываются отдельными
  строками `1C без пары в Ozon`. Такие строки не считаются ошибкой SKU-profit
  автоматически: консультант проверяет соседний месяц mutual settlement или
  отдельный Ozon-документ услуг;
- SKU-level расходы Ozon берутся из SKU-level полей realization только если
  нет принятой документной базы периода. Для V1 поддерживаются плоские поля
  `commission_amount`, `services_amount`, `logistics_amount`,
  `storage_amount`, `other_amount`;
- nested-поля realization `delivery_commission.standard_fee`,
  `return_commission.standard_fee`, `amount` и `total` не используются как
  прямой расход без отдельной документной сверки с 1C услугами. Если в Ozon
  realization есть только эти поля, `expenseStatus = partial_source`,
  расходы/profit/margin остаются `null`;
- если SKU-level расходов нет, но есть документные прямые расходы Ozon из
  mutual settlement за выбранный период, V1 распределяет эти расходы по
  товарным строкам пропорционально 1C-выручке отчета комиссионера. Строки
  получают `expenseStatus = allocated_period_expense`,
  `expenseAllocationBasis = onec_revenue_share` и видимую базу распределения;
- если нет ни SKU-level расходов, ни документной базы периода,
  `expenseStatus = partial_source`, расходы не считаются нулем и profit/margin
  остаются `null`;
- итоговая `profit = onecRevenue - COGS - Ozon API period expenses`;
- SKU-level profit считается там, где есть SKU-level расходы или явное
  распределение документных расходов периода по доле 1C-выручки. Такое
  распределение не применяется к buyout/B2B и строкам без 1C-выручки;
- `margin = profit / onecRevenue`;
- июнь и другие незакрытые периоды могут показывать realization rows, но
  `onecRevenue`, `profit` и `margin` остаются `null`, а `qualityStatus` =
  `missing_1c_commissioner`;
- buyout отображается отдельной reconciliation row/summary со статусом
  `buyout_period_only`, если номер отчета не пришел из API; buyout не
  увеличивает SKU revenue, COGS, expenses, profit или margin;
- B2B и buyout не прибавляются к SKU-выручке без документной или агрегатной
  сверки.

Совместимость: legacy-блок `unitRows` в `ozon-diagnostics` остается безопасным
bounded preview из `ozonMart.rows`, чтобы UI и внешние staff-инструменты могли
переехать без резкого изменения контракта.

`GET /api/clients/{client_id}/ozon-diagnostics/export.xlsx` - staff-only
download для проверки Ozon mart v1 по примеру Finmodel 2.0. Endpoint принимает
те же фильтры `period_start`, `period_end`, `wb_cabinet_id`, строит workbook из
полного mart preview limit, не создает `ReportRun`, не публикует клиентский
отчет и не заменяет WB Excel MVP. Workbook содержит листы:

- `Сводная Ozon`;
- `Юнит экономика Ozon`;
- `Начисления услуг Ozon`;
- `Статьи по SKU`;
- `Сверка Ozon 1C`;
- `Методика`.

Лист `Сверка Ozon 1C` показывает unmatched 1C/Ozon control rows, включая
`1C без пары в Ozon`. Такие строки не попадают в `Статьи по SKU`.

Raw payload, `Client-Id`, `Api-Key`, file paths и другие sensitive details не
должны отображаться клиентской роли. Клиентский общий итог WB+Ozon можно
включать только после mart validation и отдельной приемки нормализации Ozon.

# Mapping And Costs

Алгоритм поиска соответствия Ozon:

1. 1C `ИС_Маркетплейс` read-only Ozon mapping: `offer_id`, `product_id`,
   `sku`, barcode и название Ozon against 1C item из
   `ИС_Ozon_СоответствиеХарактеристик`.
2. Uploaded read-only mapping file: `Номенклатура Ozon` against Ozon product
   name, then `Номенклатура` against 1С nomenclature name.
3. `offer_id`/`vendor_code` against 1С article/code.
4. barcode against 1С barcode register.
5. SKU against 1С barcode register only as diagnostic fallback.
6. `product_id` or `ozon_sku` without a 1С match is diagnostic context, not a
   reliable match.

Vendor staging registers such as `ИС_Ozon_ДанныеОтчетовРеализации`,
`ИС_Ozon_ДанныеУслуг`, buyout and B2B data may be used for reconciliation and
diagnostics, but V1 revenue source remains native 1C commissioner/sales
register data. The project must not read `ИС_МП_Токены`, API profiles, passwords
or service settings through this contour.

Если `ozon_products_report` не загружен или токен не имеет доступа к товарам,
web показывает `needs_catalog_access`/`not_ready`; cash-flow source не должен
считаться товарным сопоставлением.

Запрещено приводить missing values к нулевой себестоимости. Если связь или
стоимость не найдены, строка получает `missing_mapping`, `ambiguous_mapping` или
`missing_cost`, а агрегаты получают `partial_source`.

# Calculation And Report

WB-only report must stay byte/row compatible on the same source snapshots.

Ozon facts are normalized into `marketplace_api_snapshot` first. Общие KPI по
всем маркетплейсам разрешены только когда:

- все Ozon source collections имеют `loaded` или `empty_expected`;
- Ozon mapping не содержит блокирующих ambiguous rows;
- cost snapshots покрывают нормализованные rows;
- mart validation проходит без `partial_source` в строках, которые отображаются
  как надежные.

Web/Excel должен показывать разрез `Маркетплейс`:

- WB отдельно;
- Ozon отдельно;
- общий итог только для reliable rows.

Отдельные листы/таблицы сверки:

- WB-сверка остается без изменений;
- Ozon-сверка добавляется после принятой нормализации полей realization/finance.

# Rollout

1. Deploy provider registry, Ozon config parsing, source collectors and raw
   snapshot persistence.
2. Run `source_refresh --dry-run` on tenant without Ozon and confirm WB-only
   behavior is unchanged.
3. Configure encrypted Ozon integration for one pilot tenant.
4. Run `weekly --dry-run`; inspect Ozon collections and raw manifests.
5. Enable non-published Ozon normalization QA.
6. Publish mixed report only after mart validation and consultant acceptance.

Rollback: disable `ozon_api` tenant integration or clear Ozon `.env` variables.
WB/1C collectors and published current report remain unaffected.

# Test Plan

Unit:

- parse Ozon JSON/key-value secret without leaking credentials;
- Ozon finance/products/stocks/returns exporters store raw JSON and manifests;
- Ozon contracts parse decimals and reject invalid periods;
- WB and Ozon normalize into `marketplace_api_snapshot`;
- provider registry accepts `ozon_api` roles.

Integration:

- `source_refresh` dry-run without Ozon remains WB-only compatible;
- Ozon optional collectors can fail without blocking WB/1C mandatory sources;
- local Ozon fixtures can be persisted to `source_snapshot_rows`;
- `ozon-diagnostics` returns the latest `ozon-only` run, bounded finance
  preview rows and no raw payload/secrets;
- `ozon-diagnostics` returns staff-only `ozonMart` and compatible `unitRows`
  preview without raw payload, hashes, file paths or secret markers;
- `ozon-diagnostics` extracts Ozon buyout report number and period from 1C
  `РасходнаяНакладная` comments with `ОснованиеПечати = Выкуп`, then compares
  the report number against `ozon_products_buyout`; when Ozon does not expose
  report numbers, it may reconcile the month by period total, quantity and
  amount;
- closed-month Ozon mart fixture calculates SKU profit/margin from 1C
  commissioner revenue, 1C COGS and SKU-level Ozon expenses;
- missing/ambiguous mapping, missing cost, missing 1C commissioner and missing
  SKU-level expense fields remain explicit review statuses, not zeros;
- one 1C item mapped to multiple Ozon SKU is not auto-allocated and does not
  calculate SKU profit;
- client role cannot call source-refresh or Ozon diagnostics endpoints;
- WB-only report build remains unchanged.

Security:

- `validate_no_secrets.py`;
- no `Client-Id` or `Api-Key` in Markdown, Git, API payloads or logs;
- `.env.example` contains only empty Ozon placeholders.

Acceptance:

- staff can configure and check `ozon_api` read-only integration;
- staff can see a separate `Диагностика Ozon + 1C` block near the top of the
  client page with latest Ozon/1C source collection statuses and row counts;
- staff can see an `Ozon v1` calculation vitrina where revenue comes from the
  1C sales register for `ООО Интернет Решения`, commissioner report is shown as
  reconciliation context, and Ozon cash-flow is not shown as revenue;
- staff can see the final Ozon vs 1C revenue formula:
  `commissioner/realization + buyout = 1C sales register`, including the final
  delta;
- staff can see a separate `Выкупы Ozon` block where 1C expense invoices are
  reconciled by Ozon buyout report number or, when the API lacks that number,
  by the monthly period total with amount/quantity and found/not found status
  against Ozon API;
- staff can see Ozon issue cards analogous to WB analytics prompts; `missing`
  and `ambiguous` mapping rows are surfaced for accountant correction instead
  of being auto-fixed by the app;
- staff can see `Ozon mart / Детализация SKU` with 1C revenue, quantity, COGS,
  SKU-level Ozon expenses, profit, margin and the reason/action for every
  review row;
- staff can see `Ozon mart.articleRows` and the web P&L table broken down by
  Finmodel-style articles rather than only one aggregated marketplace expense
  line;
- staff can download `Excel Ozon` from the Ozon + 1C diagnostics block; the
  export includes Finmodel-style article sheets, SKU article rows and Ozon/1C
  reconciliation, while unmatched 1C-only rows stay out of SKU-profit sheets;
- clients without WB can run `ozon-only` and see Ozon + 1C diagnostics without
  publishing a unit economics report;
- refresh can collect Ozon raw snapshots by source type;
- incomplete Ozon source produces `needs_review`/`partial_source`, not zeros;
- repeated build from the same snapshots is reproducible;
- existing WB-only report path does not change unless mixed-marketplace report
  is explicitly enabled.

# Changelog

- 2026-07-08: Added Finmodel 2.0 inspired Ozon article breakdown for mart v1:
  `articleRows` in the mart payload and per-SKU `expenseArticles`, while keeping
  the accepted mutual-settlement/1C calculation basis unchanged.
- 2026-07-08: Added staff-only Ozon diagnostics Excel export and
  `articleDrilldown`: article-to-SKU allocations are separated from Ozon/1C
  reconciliation rows so unmatched 1C-only documents remain visible but do not
  affect SKU-profit.
- 2026-07-08: Added article-level expense reconciliation rows for 1C service
  documents without Ozon API pair in the selected month, including a visible
  hint to check adjacent mutual-settlement periods or separate Ozon service
  documents.
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
