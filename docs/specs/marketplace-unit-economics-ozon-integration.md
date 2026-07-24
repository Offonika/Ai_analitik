---
spec_id: "marketplace-unit-economics-ozon-integration"
title: "Marketplace unit economics: Ozon integration"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
truth_scope: ozon
truth_priority: 100
related_code: [src/wb_unit_economics/ozon.py, src/wb_unit_economics/ozon_mart.py, src/wb_unit_economics/source_integrity.py, src/wb_unit_economics/marketplace.py, src/wb_unit_economics/contracts.py, src/wb_unit_economics/config.py, src/wb_unit_economics/onec_odata.py, src/wb_unit_economics/web/source_refresh.py, src/wb_unit_economics/web/repository.py, src/wb_unit_economics/web/settings.py, src/wb_unit_economics/web/providers.py, src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/static/app.js, scripts/materialize_ozon_typed_facts.py, scripts/compare_ozon_legacy_typed.py, scripts/restore_marketplace_raw_rows.py, scripts/migrate_ozon_tax_profiles.py]
related_tests: [tests/test_ozon.py, tests/test_ozon_mart.py, tests/test_ozon_typed_parity.py, tests/test_source_integrity.py, tests/test_restore_marketplace_raw_rows.py, tests/test_migrate_ozon_tax_profiles.py, tests/test_marketplace_daily_facts.py, tests/test_contracts.py, tests/test_provider_registry.py, tests/test_source_refresh.py, tests/test_web_app.py]
contracts: [ozon_api_snapshot, ozon_product_snapshot, ozon_stock_snapshot, ozon_sku_mapping, marketplace_api_snapshot, unit_economics_report]
depends_on: [docs/specs/wb-unit-economics-db-first-report-marts.md, docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md, docs/specs/marketplace-1c-mapping-service.md]
changelog_path: docs/changelogs/ozon-integration.md
ai_sections:
  status: "Implementation Status"
  goal: "Goal"
  canonical_pnl: "Canonical Ozon P&L v2"
  scope: "Scope"
  api_sources: "Ozon API Sources"
  provider_registry: "Provider Registry"
  source_refresh: "Source Refresh"
  contracts: "Data Contracts"
  preview: "Web Preview"
  mart: "Ozon Unit Economics Mart v1"
  mapping_costs: "Mapping And Costs"
  rollout: "Rollout"
  tests: "Test Plan"
code_anchors:
  - path: src/wb_unit_economics/ozon_mart.py
    symbols: ["def build_ozon_unit_economics_mart", "def combine_ozon_monthly_marts"]
supersedes: []
rollout_required: true
updated_at: "2026-07-21"
---

# Implementation Status

Статус остается `accepted`. Read-only collector, marts, mapping и web diagnostics
реализованы и имеют целевые тесты, но полный mixed-report acceptance и
production rollout не доказываются только changelog. Непроверенные критерии
остаются основанием не повышать spec до `implemented`.

# Goal

Добавить Ozon как второй read-only маркетплейс в финмодель WB/1C без
регрессии существующего WB-контура.

V1 не заменяет WB-методику. V1 добавляет provider `ozon_api`, raw snapshots
Ozon и общий контракт `marketplace_api_snapshot`, где `marketplace` принимает
значения `wb` или `ozon`. Для клиентов без WB допускается диагностический
режим `ozon-only`: он читает Ozon + 1C, сохраняет source snapshots и после
успешного недемонстрационного запуска создает внутренний `draft`-отчет с
`lineage_type = ozon_mart_snapshot`, закрепленный за конкретным immutable
source refresh. Такой черновик виден только staff и не публикуется клиенту до
mart validation и отдельной финансовой приемки. Смешанный отчет WB+Ozon можно
публиковать только после той же приемки.

# Canonical Ozon P&L v2

Единственный канонический расчет Ozon строится месячными корзинами в границах
одной организации 1С. Для каждого месяца Ozon realization, отчет комиссионера,
себестоимость регистра продаж и расходы mutual settlement относятся к одному
`client_company_id`, `onec_organization_id` и календарному месяцу. Стоимость
индексируется по `organization_id + onec_item_id + month`; средняя стоимость
всего snapshot запрещена. Если организация 1С не выбрана, строки других
организаций не используются как fallback: закрытый месяц получает
`missing_1c_organization`, попадает в `excludedIncompletePeriods`, а финансовые
итоги и прибыль не публикуются до решения аналитика.

Signed-движения регистра продаж сначала агрегируются внутри документа по ключу
`organization_id + onec_item_id + month + document_id + counterparty_id`.
Количество и выбранная
себестоимость суммируются раздельно, поэтому строки одного документа с
количеством и стоимостью в разных движениях остаются связанными. Документ
участвует в unit cost только при ненулевом итоговом signed-количестве;
стоимостные движения документа с нулевым количеством остаются только в
сверке и не присоединяются к продажам другого документа. Если `Документ` или
`Recorder` отсутствует, fallback ограничивается одной исходной строкой
snapshot и не объединяет независимые строки. Для прямого Ozon-контроля строка
стоимости без контрагента наследует контрагента snapshot только при единственном
контрагенте в этой строке. Маркированные движения разных контрагентов внутри
одного Recorder не складываются. Любая неразмеченная quantity/cost строка при
нескольких контрагентах дает `direct1cStatus = not_available`, даже если
Recorder указан; система не выбирает одного автоматически.

Компания хранит отдельный `onec_organization_id`; существующий текстовый
`source_key` не переопределяется. Автосвязь разрешена только по уже
сохраненному точному `Ref_Key` либо по единственному точному совпадению полного
названия без нечеткого поиска. Один непривязанный Ozon-кабинет можно связать с
единственной компанией клиента автоматически с записью в audit. Все остальные
случаи получают `needs_review`. Наличие ровно одной компании и одной организации
1С без совпадения имени не является основанием для автосвязи.

Налоговый профиль является неизменяемым снимком организации 1С с периодом
действия, `source_refresh_run_id`, hash источника и версией методики. Приоритет:
явный профиль 1С, затем действующее аудируемое ручное исключение, затем
`missing`. Ручное исключение обязательно хранит автора, причину и срок
действия. Поле учета страховых взносов не определяет УСН; автоматический
`legacy-default` запрещен. Отсутствие уведомления о спецрежиме не доказывает
ОСНО.

Месяц без закрывающего отчета комиссионера получает
`missing_1c_commissioner`; `onecRevenue`, COGS, расходы, прибыль и маржа для
этого месяца не публикуются. Если диапазон содержит такой месяц, общие
`profit`/`margin` равны `null`, а API отдельно возвращает
`closedPeriodTotals` и `excludedOpenPeriods`.

Для закрытого месяца API отдельно оценивает `costQuality`. Стоимость строится
из знаковых движений 1С без `abs()` и без средней по всему snapshot. Для SKU
референсом является медиана не более трех предыдущих закрытых месяцев по той
же организации и номенклатуре. Менее двух месяцев истории дает
`insufficient_history`. Стоимость ниже 50% или выше 200% референса является
аномалией. Аномалии блокируют месяц, если суммарное предполагаемое влияние не
меньше `max(100 000 рублей; 0,5% месячной выручки)`. Отсутствующая или
неположительная стоимость блокирует месяц всегда. Несущественная ненулевая
аномалия дает `warning`, но не скрывает прибыль.

`ozonMart.costQuality` возвращает покрытие по выручке и количеству, количество
аномальных SKU, предполагаемое влияние, порог существенности и отклонение
средней стоимости mart от прямого регистра 1С по Ozon. Строки дополнительно
возвращают `costQualityStatus`, `referenceUnitCost`, `unitCostDeviationPct`,
`estimatedCostImpact` и `costQualityReason`. Закрытый месяц с блокирующей
неполнотой попадает в `excludedIncompletePeriods` и не входит в
`closedPeriodTotals`; `excludedOpenPeriods` используется только для
незакрытого отчета комиссионера. Общие profit/margin диапазона с любым
исключенным месяцем равны `null`.

Покрытие количества считается по всей положительной реализации месяца,
включая несопоставленные и неоднозначные строки. `revenueCoveragePct` равен
`null`, если полная выручка неизвестна из-за таких строк. Для прозрачной
диагностики API отдельно возвращает `eligibleRevenueAmount`,
`coveredEligibleRevenueAmount`, `eligibleRevenueCoveragePct`,
`unmappedQuantity`, `ambiguousQuantity`, `unmappedRevenueRowCount` и
`ambiguousRevenueRowCount`. Несопоставленная строка с ненулевой суммой делает
`revenueCoveragePct = null` даже при нулевом или отрицательном количестве.
Строка с положительным количеством, но нулевой суммой влияет только на
`quantityCoveragePct` и не делает известное покрытие выручки пустым.

Прямой контроль регистра 1С имеет `direct1cStatus = available` только при
положительных signed quantity и COGS. При положительном количестве и нулевой
или отрицательной стоимости API возвращает `direct1cStatus = not_available` и
`direct1cReason = nonpositive_cost`; такая сверка не изображается готовой.

Порог существенности применяется отдельно к каждому месяцу. Месячный mart
возвращает фактический `materialityThresholdAmount`. Для диапазона из нескольких
месяцев это поле равно `null`, а `materialityThresholdMode = monthly` и поля
`materialityThresholdMinAmount`/`materialityThresholdMaxAmount` показывают
границы реально примененных месячных порогов; порог от суммарной выручки
диапазона не пересчитывается.

Строки и итоги возвращают `profitBeforeTax`, `marginBeforeTax`, `vatOutput`,
`vatInput`, `vatPayable`, `revenueTax`, `incomeTax`,
`profitBeforeIncomeTax`, `profitAfterTax`, `marginAfterTax`, `taxSystem`,
`taxProfileSource` и `taxCompleteness`. Временное поле `profit` является
deprecated alias для `profitBeforeTax`. Для ОСНО P&L без НДС допускается
только при подтвержденной выручке, себестоимости без НДС и входящем НДС. Без
годовой базы НДФЛ `profitAfterTax` не публикуется; UI показывает
«Управленческая прибыль до налогов».

Для ОСНО подтверждается только товарный входящий НДС из регистра продаж 1С.
Входящий НДС по услугам Ozon (комиссия, логистика, хранение, прочие сборы)
несет НДС внутри, но его вычет отдельным источником 1С не подтвержден и в
`vatInput`/`vatPayable` не включается. Если у строки ОСНО есть сервисные
расходы Ozon, `taxCompleteness` строки равен
`vat_input_partial_ndfl_not_allocated` (review), а не
`vat_confirmed_ndfl_not_allocated`: `НДС к уплате` помечается как требующий
проверки и не занижается недоказанным сервисным вычетом.

Налоговая неполнота выходит в `issues` отдельными карточками и попадает в
очередь аналитика, не искажая неналоговые показатели: отсутствие профиля дает
`ozon_mart_tax_profile_missing`, неполный или отсутствующий входящий НДС (в том
числе `input_vat_missing` и `vat_input_*_ndfl_not_allocated`) дает
`ozon_mart_tax_input_vat_review`.

В Excel и статье P&L `vatPayable`, `revenueTax` и `incomeTax` имеют отрицательное
`effectAmount`. `vatOutput` и `vatInput` являются строками налогового моста с
`effectAmount = null` и не складываются повторно с `vatPayable`.
`profitAfterTax` остается итоговой строкой результата.

Legacy-блок `pnl` сохраняется только в staff API с `deprecated = true` и
`replacement = ozonMart`; UI его не отображает. Staff API также предоставляет
явный выбор организации 1С и создание/отключение временного налогового
исключения.

В пределах одного refresh run позиция строки уникальна по
`refresh_run_id + collection_id + row_number`. Повтор payload hash является
отдельной ошибкой качества: snapshot и mart получают `needs_review`, прибыль
блокируется, а строки не удаляются молча. Исторические snapshots разных
refresh run не считаются дублями; расчет всегда использует один run.
Dry-run хранится в аудите готовности, но никогда не становится источником
`ozonMart` и не скрывает последний реальный immutable snapshot. Источником
расчета является последний завершенный недемонстрационный `ozon-only` run со
статусом `source_loaded` или `needs_review`. Более новая активная или
неуспешная попытка возвращается отдельно как `latestAttempt` и не заменяет
совместимое поле `latestRun`, указывающее на фактический расчетный snapshot.

Коллекция 1С `commissioner_reports` обязана содержать не только заголовки
документов, но и `Организация_Key` и финансовые табличные части `Запасы` и
`ЗапасыВозвраты`.
Загруженные заголовки при отсутствии всех товарных строк имеют статус
`partial_source` с кодом `commissioner_financial_tables_missing`. Такой
структурно неполный `ozon-only` snapshot остается доступен для диагностики, но
не создает новый Ozon draft и не скрывает последний воспроизводимый черновик.
Отсутствующий `Организация_Key` аналогично дает
`commissioner_organization_missing`: организационный scope не угадывается.
Если полный raw-файл превышает общий лимит DB persistence, он остается
авторитетным immutable-источником, а в `source_snapshot_rows` сохраняется
компактная копия заголовков и только финансово значимых полей товарных строк.
Mart обязан рассчитываться из этой компактной копии того же refresh run; чтение
«последнего файла вообще» или другого snapshot запрещено.
Отсутствие конкретного документа 1С внутри корректно загруженного источника
по-прежнему создает `needs_review` и показывается в документной сверке.

Диапазон агрегирует `rowCount`, `summary`, `totals` и `closedPeriodTotals` из
помесячных mart, а не из ограниченного массива preview-строк. `rows` остается
только витринным preview; `previewLimited = true`, когда полный `rowCount`
больше количества возвращенных строк.

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

Источник по отключению старых финансовых методов: официальная
[документация Ozon Seller API](https://docs.ozon.ru/api/seller/) и changelog в
кабинете продавца. В зафиксированном уведомлении указано, что 6 июля 2026 года
методы
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

Для multi-account JSON каждый элемент `accounts` обязан быть object и содержать
полную пару `clientId`/`apiKey`. Один невалидный элемент отклоняет весь secret с
безопасным индексом элемента; молчаливое исключение отдельного кабинета запрещено.

Секреты не выводятся в API payload, logs, Markdown, Git или validation errors.

# Source Refresh

Каждый Ozon/1C refresh читает периодические настройки налогового профиля из
`InformationRegister_СистемыНалогообложенияОрганизаций` и
`InformationRegister_НастройкиУчетаНДС`. Профиль разрешается отдельно для
каждой связанной организации по состоянию на дату строки/периода; настройки
одной организации не используются как fallback для другой.

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

Все period-based exporters отклоняют `period_start > period_end` до записи
файлов и сетевых запросов. Асинхронный report polling проверяет `result.status`,
`result.error` и наличие file URL. По умолчанию он выполняется не дольше 300
секунд с интервалом 5 секунд; terminal failure, success без файла и timeout
остаются явными partial-source статусами. Исчерпание `max_pages` при непустой
последней странице также является partial source, а не успешным окончанием.

Диагностическая витрина `ozon-only`:

- доступна только staff-пользователям через
  `GET /api/clients/{client_id}/ozon-diagnostics`;
- берет последний `source_refresh_runs` с `mode = ozon-only` для выбранного
  клиента;
- поддерживает безопасные query-фильтры `period_start`, `period_end` и
  `wb_cabinet_id`, чтобы показатели Ozon пересчитывались под выбранный период и
  Ozon-кабинет;
- если клиентский отчет не создан, блок «Контроль перед отправкой» явно
  показывает, что report-level проверка недоступна, и выводит доступную
  диагностику Ozon + 1C вместо пустого состояния загрузки;
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
- `rawContentSha256` для новых snapshot;
- `reportStatus`;
- `pageLimitExhausted`;
- `outputFile`;
- `reportCode`;
- `error`.

Новые JSON snapshots сохраняют точные байты успешного HTTP response body.
`rawPayloadHash` остается совместимым semantic hash, а `rawContentSha256`
проверяет byte-exact immutable файл. Старые snapshots без byte hash продолжают
проверяться по legacy semantic hash.

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
barcode, product name) с 1С. Подтверждение и исправление связи выполняются
только в собственном mapping service (сервисе сопоставления) проекта. Файл
`Номенклатура Ozon` -> `Номенклатура` и расширение 1С импортируют read-only
кандидатов, но не являются источником принятого решения. Статусы: `matched`,
`missing`, `ambiguous`, `excluded`.

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
Верхние KPI витрины `Выручка 1C Ozon` и `Себестоимость 1C` показывают прямые
итоги того же регистра, включая подтвержденные дополнительные документы,
например выкупы. Итоговый P&L Ozon использует ту же базу и поэтому включает
выкупы. SKU-строки по реализации/отчету комиссионера остаются детализацией:
дополнительные документы без подтвержденной связи с товаром не распределяются
по SKU, но входят в выручку, себестоимость и итоговую прибыль Ozon.
До появления в снимке 1C подтвержденного поля `СебестоимостьБезНДС` и
входящего НДС себестоимость берется из поля 1C `Себестоимость` без собственной
корректировки НДС. Витрина помечает это как «НДС не выделен» и не называет
такую сумму себестоимостью без НДС.
В Ozon v1 витрине должна быть отдельная сверка выручки. Карточка
`Выручка 1C Ozon · факт` берется только из 1C OData
`AccumulationRegister_Продажи` по Ozon-контрагенту и включает все проведенные
документы выбранного периода, в том числе выкупы. Эта карточка не является
данными Ozon API или WB API и не должна подменяться ими при отсутствии 1C.

Контрольная формула первички:
`Ozon API realization + Ozon API buyout = 1C регистр продаж`.
Ozon realization и Ozon buyout образуют ожидаемую сумму первичных документов,
а регистр продаж 1C является бухгалтерским фактом. Отчет комиссионера 1C и
расходные накладные выкупов показываются между ними как документная
расшифровка, но не используются вместо Ozon API в левой части формулы.
Диагностика отдельно показывает дельту отчета комиссионера, дельту выкупов и
общую дельту регистра.

Для каждого вида первички диагностика возвращает один из статусов:
`matched`, `missing_in_1c`, `not_posted`, `wrong_date`, `amount_mismatch` или
`missing_ozon_source`. Для отчета комиссионера период извлекается из комментария
1C; если отчет относится к выбранному месяцу, но дата документа выходит за его
границы, документ должен оставаться видимым со статусом `wrong_date`. UI
показывает номер и дату документа, проблему и конкретное действие бухгалтеру.
После исправления в 1C кнопка `Перепроверить после исправления` запускает только
read-only обновление `ozon-only`; кабинет не создает, не меняет и не проводит
документы 1C автоматически.

Если контрольная формула сходится, дельта Ozon API vs 1C показывается как `0`,
даже если buyout подтвержден не по номеру отчета, а по контрольному агрегату.
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
карточки не исправляют данные автоматически. Ответственный пользователь
подтверждает или исправляет `missing` и `ambiguous` в собственном сервисе
сопоставления, после чего консультант повторяет `Ozon + 1C` refresh. Файлы и
расширение 1С могут только обновить кандидатов. Если критичных проблем нет,
блок показывает спокойный
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
  контроля суммы периода, сверки с 1C услугами и распределения только остатка
  без SKU-атрибуции;
- project-owned mapping service - приоритетная связь Ozon -> 1C из
  подтвержденных оператором decisions; 1C `ИС_Маркетплейс 3.5.57.0` и старый
  HTTP-сервис `offonika` могут импортироваться только как read-only кандидаты;
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
- приходная накладная 1C с операцией `ВозвратОтКомиссионера` или маркером
  отчета о выкупленных товарах не является расходом услуг Ozon: она исключается
  из дельты расходов и остается контекстом отдельной сверки выкупов. Для
  `Document_ПриходнаяНакладная` snapshot обязан сохранять `ВидОперации`;
  отсутствующая или неизвестная операция получает `unclassified` и не
  включается в контроль расходов до проверки;
- Ozon buyout reconciliation - отдельная сверка, не часть SKU profit;
- Ozon mapping diagnostics - статус связи Ozon -> 1C.

Контракт `ozonMart`:

- `status`, `summary`, `totals`, `rows`, `issues`, `previewLimit`,
  `previewLimited`;
- `expenseAttribution` - контроль базы расходов: `skuAttributedExpenseAmount`,
  `periodExpenseAmount`, `unattributedExpenseAmount`,
  `allocatedUnattributedExpenseAmount`, `overAttributedExpenseAmount`,
  `periodExpenseDeltaAmount`, `roundingDeltaAmount`, `status`,
  `allocationBasis`;
- `articleRows` - Finmodel-compatible P&L breakdown by article. The first
  release keeps the same calculation basis as mart v1, but exposes the result
  as readable rows: 1C revenue, Ozon commission, Ozon services, partner/rebilled
  services, logistics, storage, promotion/other/compensations when available,
  1C COGS and pre-tax profit;
- row fields: `periodStart`, `periodEnd`, `offerId`, `productId`, `sku`,
  `barcode`, `productName`, `onecItemId`, `onecName`, `quantity`,
  `onecRevenue`, `unitCost`, `cogs`, `ozonCommission`, `ozonServices`,
  `ozonPartnerServices`, `ozonLogistics`, `ozonStorage`, `ozonOtherExpenses`,
  `skuAttributedExpenseAmount`, `periodUnattributedExpenseAmount`,
  `expenseBasis`, `expenseAttributionType`, `expenseAllocationBasis`, `profit`,
  `margin`, `qualityStatus`, `expenseStatus`, `problemReason`, `actionText`;
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
- несколько внутренних Ozon `sku`/`product_id` по одному seller `offer_id`
  считаются одной товарной идентичностью для mart; это не блокирует
  `onecRevenue`, COGS и profit;
- если fallback-сопоставление по seller `offer_id`/артикулу 1C дает несколько
  1C-кандидатов, mart может снять неоднозначность только когда ровно один
  кандидат присутствует одновременно в 1C отчете комиссионера и в 1C регистре
  себестоимости выбранного периода. Такое сопоставление получает метод
  `*_period_financials`; если таких кандидатов ноль или больше одного, строка
  остается `ambiguous_mapping`;
- COGS считается по 1C cost index только для однозначно сопоставленных строк;
- quantity и COGS являются знаковыми: `quantity = sales - returns`, возврат
  восстанавливает COGS, а нулевое net quantity с валидной unit cost дает COGS 0;
- расходы Ozon по SKU из Ozon realization/detail полей являются первичной базой
  товарной прибыли, если источник явно отдает сумму по конкретной SKU-строке;
- для Ozon realization/detail комиссия SKU берется только из явных flat-полей
  комиссии. Вложенные `delivery_commission.standard_fee`,
  `return_commission.standard_fee`, `amount` и `total` не являются прямым
  SKU-расходом V1;
- Ozon mutual settlement используется как документный контроль периода и состава
  статей, а не как причина перезаписать уже найденные SKU-level расходы;
- если mutual settlement больше суммы SKU-level расходов, положительный остаток
  `periodExpenseAmount - skuAttributedExpenseAmount` распределяется по доле
  1C-выручки только как fallback `period_unattributed`;
- если SKU-level расходы покрывают весь период, fallback-распределение не
  создается; расхождение до 1 ₽ или 0.05% показывается как округление;
- если SKU-level расходы больше mutual settlement, отрицательный остаток не
  распределяется и показывается контрольной строкой `Ozon detail больше mutual
  settlement`;
- fallback всегда ограничен глобальным положительным остатком периода. Остатки
  отдельных статей могут задавать веса распределения, но не могут увеличить
  общую SKU-атрибуцию сверх `periodExpenseAmount - skuAttributedExpenseAmount`;
- 1C используется для контроля полноты разнесения расходов, но 1C-only услуги
  без пары в Ozon API не добавляются в SKU-profit;
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
- каждый запрошенный месяц без realization rows явно попадает в
  `excludedIncompletePeriods`; только доказанный незакрытый месяц может быть
  отнесен к `excludedOpenPeriods`;
- decimal fallback продолжает поиск после null/empty/unparseable primary key.
  Если присутствующие aliases не содержат ни одного числа, строка остается
  partial source, а значение не превращается в ноль;
- 1C услуги Ozon без пары в API за выбранный месяц показываются отдельными
  строками `1C без пары в Ozon`. Такие строки не считаются ошибкой SKU-profit
  автоматически: консультант проверяет соседний месяц mutual settlement или
  отдельный Ozon-документ услуг;
- SKU-level расходы Ozon берутся из SKU-level полей realization/detail как
  первичная товарная атрибуция: плоские `commission_amount`,
  `services_amount`, `logistics_amount`, `storage_amount`, `other_amount`.
  Вложенные `delivery_commission.standard_fee`,
  `return_commission.standard_fee`, `amount` и `total` не используются как
  расходная комиссия;
- если SKU-level расходов нет, но есть документные прямые расходы Ozon из
  mutual settlement за выбранный период, V1 распределяет эти расходы по
  товарным строкам пропорционально 1C-выручке отчета комиссионера. Строки
  получают `expenseStatus = allocated_period_expense`,
  `expenseAllocationBasis = onec_revenue_share` и видимую базу распределения;
- строка mutual settlement `Отчет о реализации` является контрольной строкой
  реализации/взаиморасчетов и не включается в прямые расходы или комиссию Ozon;
  комиссия периода может попасть в P&L только из явных SKU-level commission
  полей или из явно названных комиссионных/вознаграждения;
- дебетовая часть `Отчета о реализации` может сверяться по точной сумме с
  документом услуг 1C как `control_matched`. Такая пара уменьшает только
  необъясненную дельту сверки и не добавляется повторно в расходы или SKU-profit;
- если нет ни SKU-level расходов, ни документной базы периода,
  `expenseStatus = partial_source`, расходы не считаются нулем и profit/margin
  остаются `null`;
- итоговая `profitBeforeTax = onecRevenue - COGS - SKU-level Ozon expenses -
  allocated period residual`;
- `profit` временно повторяет `profitBeforeTax` и помечается deprecated;
- SKU-level profit считается там, где есть SKU-level расходы или явное
  распределение документных расходов периода по доле 1C-выручки. Такое
  распределение не применяется к buyout/B2B и строкам без 1C-выручки;
- `marginBeforeTax = profitBeforeTax / onecRevenue`; `margin` временно
  повторяет `marginBeforeTax`;
- июнь и другие незакрытые периоды могут показывать realization rows, но
  `onecRevenue`, COGS, расходы, `profit` и `margin` остаются `null`, а
  `qualityStatus` =
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

1. Project-owned mapping service current view: accepted Ozon -> 1C decisions,
   ручные решения и audit имеют приоритет над автоматическими кандидатами.
2. Кандидаты из 1C `ИС_Маркетплейс` read-only Ozon mapping или uploaded file:
   `offer_id`, `product_id`, `sku`, barcode, `Номенклатура Ozon` against Ozon product
   name, then `Номенклатура` against 1С nomenclature name; такие совпадения
   требуют решения в сервисе проекта.
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

Нерешенные сопоставления и налоговые профили система не исправляет
автоматически. Они остаются видимой очередью аналитика; пока их влияние
блокирует месяц, `profitBeforeTax = null` и месяц перечислен в
`excludedIncompletePeriods`.

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

1. Run `scripts/migrate_ozon_tax_profiles.py` without `--apply`; record only
   aggregate candidate/duplicate counts and do not change live data.
2. Stop if any active source refresh or position duplicate exists. Apply the
   migration only after the refresh is finished; the unique position index is
   created concurrently on PostgreSQL.
3. Apply only exact unambiguous company/organization and single-company Ozon
   cabinet links. Leave all other links for the staff API.
4. Reduce snapshot persistence batches to 1,000 rows. Commit each completed
   batch. On PostgreSQL `OperationalError`, mark the immutable run `failed` and
   resume only in a new run from the saved 1C checkpoint; never retry a
   transaction with unknown outcome inside the same run.
   `ozon-only` preflight requires Ozon + 1C and does not block on an unrelated
   WB integration status.
   `ozon-only` resume creates a new run, reuses only the verified 1C checkpoint
   and recollects every Ozon source.
5. Reload the first pilot client in `ozon-only`, validate one closed month, then
   inspect an incomplete and an open month. Keep `taxProfile.status = missing`
   when 1C has no explicit regime; do not add an override without accountant
   confirmation.
6. Validate a second pilot client for one closed month against 1C, then repeat
   the same contract for the next client only after the pilot checks pass.
   Publish a mixed report only after consultant acceptance. Exact client ids and
   periods belong to local acceptance evidence outside Git.

Rollback: keep the new additive tables/column, disable the new mart/UI path and
restore the previous application version. Do not delete snapshots, profiles or
audit rows; WB/1C read-only collectors and the published current report remain
unaffected.

# Test Plan

Unit:

- parse Ozon JSON/key-value secret without leaking credentials;
- Ozon finance/products/stocks/returns exporters store raw JSON and manifests;
- Ozon contracts parse decimals and reject invalid periods;
- report polling covers waiting, success, terminal failure, success without a
  file and timeout; pagination exhaustion is explicit;
- raw JSON round-trips byte-exact with a content hash while legacy manifests
  remain verifiable;
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
- monthly mart uses period cost by organization and item; a later open month
  cannot change the result of earlier closed months;
- an anonymized closed-period fixture reconciles 1C revenue, Ozon expenses,
  signed monthly COGS and pre-tax profit; mart average unit cost must stay within
  the accepted tolerance of the direct 1C register average;
- controls derived from a whole-snapshot average are superseded; a multi-month
  control is accepted only when every included month is complete;
- non-material cost anomaly returns `warning`; material anomaly, missing or
  nonpositive cost returns `blocked` and null profit. A closed incomplete May
  is listed in `excludedIncompletePeriods`; open June is listed only in
  `excludedOpenPeriods`;
- an anonymized incomplete-period fixture keeps profit `null` and exposes
  missing-cost, ambiguous-mapping and incomplete-expense blockers separately;
  exact production report ids, snapshot ids and business totals stay in local
  acceptance evidence outside Git;
- tax profile tests cover explicit 1C USN, OSNO with confirmed input VAT,
  missing profile, missing annual NDFL base, overlapping profiles and multiple
  organizations of one client;
- OSNO rows with Ozon service expenses expose `taxCompleteness`
  `vat_input_partial_ndfl_not_allocated` and an `ozon_mart_tax_input_vat_review`
  issue instead of a confirmed label; missing profile and unconfirmed input VAT
  reach the analyst queue as `ozon_mart_tax_profile_missing` /
  `ozon_mart_tax_input_vat_review` issues without distorting non-tax figures;
- resolution without a refresh run picks the tax profile of the most recent 1C
  run valid on the date, never a stale prior run whose profile only has a later
  `valid_from`;
- exact repeated payload blocks mart; legitimate different rows are never
  removed merely because a technical source identifier repeats;
- pure returns keep negative quantity/COGS, zero-net rows with valid cost are
  complete, and a missing middle month blocks range totals;
- period expense allocation never exceeds the positive global residual;
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
- staff can see one canonical profit, the period-close status, COGS coverage,
  anomaly impact and the source of the tax profile; the superseded April
  control is not shown in UI;
- staff can see `Ozon mart.articleRows` and the web P&L table broken down by
  Finmodel-style articles rather than only one aggregated marketplace expense
  line;
- staff can see whether Ozon expenses are `по SKU`, `нераспределенный остаток`
  or `сверка 1C/Ozon`; UI and Excel expose `База расхода`, `Тип атрибуции` and
  `Остаток периода`;
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

Полная история изменений вынесена в `docs/changelogs/ozon-integration.md`.
