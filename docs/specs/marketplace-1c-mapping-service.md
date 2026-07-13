---
spec_id: "marketplace-1c-mapping-service"
title: "Own marketplace/1C mapping service"
doc_type: spec
domain: "marketplace-analytics"
status: implemented
owner: "engineering"
audience: ["engineering", "consultant", "operations"]
source_of_truth: true
truth_scope: mapping
truth_priority: 100
related_code: [src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/mapping_service.py, src/wb_unit_economics/web/models.py, src/wb_unit_economics/web/source_refresh.py, scripts/check_source_refresh_preflight.py, sql/web_cabinet_schema.sql]
related_tests: [tests/test_mapping_service.py, tests/test_source_refresh.py, tests/test_source_refresh_preflight.py, tests/test_web_app.py]
contracts: [sku_mapping, sku_mapping_snapshot, ozon_sku_mapping]
depends_on: [docs/specs/wb-unit-economics-excel-mvp-implementation.md, docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md]
related_specs: [docs/specs/marketplace-unit-economics-ozon-integration.md]
supersedes: [docs/specs/onec-marketplace-mapping-http-service.md, docs/specs/onec-marketplace-mapping-client-extension.md]
rollout_required: true
updated_at: "2026-07-13"
---

# Goal

Сделать собственный сервис сопоставления товаров 1С и маркетплейсов внутри
существующего web-кабинета проекта. Сервис становится источником правды для
`sku_mapping`: он хранит подтвержденные оператором связи, кандидатов,
статусы качества и журнал решений.

Предыдущая идея получать готовое сопоставление из расширения 1С
`ИС_Маркетплейс` больше не является основным путем. 1С, WB и Ozon остаются
read-only источниками справочников и фактов, а решения по связям хранятся в
нашей БД.

Дизайн берет за основу контур MM competitor matching: большая таблица исходных
товаров, панель кандидатов, действия `accept`, `reject`, `revoke`, явные
статусы уверенности и append-only журнал решений.

# Scope

Входит:

- staff-only UI в web-кабинете для сопоставления маркетплейс-товаров с 1С;
- поддержка WB и Ozon как `marketplace`;
- импорт read-only кандидатов из WB product cards, Ozon product snapshots и
  1С OData;
- импорт старых TXT/TSV/CSV или 1С `ИС_Маркетплейс` данных как массовый
  сценарий подтверждения: однозначные строки становятся текущими связями
  `sku_mapping`, конфликтные и неполные строки остаются кандидатами для ручной
  проверки;
- автоматические кандидаты по артикулу, barcode, offer id, SKU, названию и
  нормализованным признакам;
- автоматическое принятие единственного точного barcode-кандидата из живого
  read-only снимка 1С для еще не сопоставленного товара;
- ручные действия оператора: принять связь, отклонить кандидата, снять связь,
  исключить товар из расчета;
- журнал решений с пользователем, причиной, временем и предыдущим статусом;
- экспорт подтвержденных связей в расчетный `sku_mapping`;
- явные внутренние статусы `missing`, `ambiguous`, `needs_review`, `excluded`;
  наружу в расчетный `MappingStatus` не экспортируется `needs_review`: он
  превращается в `missing` или `ambiguous` с человекочитаемым комментарием;
- интеграция с readiness/source refresh: отчет не публикуется как полностью
  готовый, если обязательные mapping-связи отсутствуют или неоднозначны.

Не входит:

- запись в WB, Ozon, 1С, банк, CRM, Bitrix или email;
- изменение номенклатуры, характеристик, документов или регистров 1С;
- автоматическое массовое принятие слабых fuzzy/LLM-кандидатов без отдельного
  accepted spec;
- перенос бизнес-логики в Bitrix24;
- хранение raw клиентских выгрузок или отчетов в Git/Markdown;
- публикация полного OData или HTTP-интерфейса 1С наружу.

# User Roles And Business Decisions

Роли:

- `admin` настраивает read-only интеграции и права пользователей;
- `consultant` импортирует готовые сопоставления из файла, проверяет очереди и
  вручную принимает оставшиеся связи;
- `client` видит итоговые статусы данных в отчете, но не меняет mapping в MVP.

Бизнес-решения:

- собственный сервис является владельцем подтвержденного mapping;
- 1С остается источником себестоимости, номенклатуры, характеристик и
  штрихкодов, но не владельцем решений по связям с маркетплейсом;
- WB/Ozon остаются источником карточек, offer/SKU/barcode и факта продаж;
- связь из файла имеет приоритет над автоматическим кандидатом, а ручное
  решение оператора имеет приоритет над обоими сценариями;
- слабое совпадение не превращается в расчетную связь без явного accept;
- единственный логический товар 1С по точному штрихкоду с `confidence=1` и
  `matchCount=1` считается уже подтвержденным первичным источником и принимается
  системой без повторного ручного подтверждения;
- автоматическое принятие никогда не заменяет ручную, файловую или ранее
  принятую связь; расхождение с живым точным штрихкодом попадает в отдельный
  staff-only счетчик конфликтов;
- если один marketplace item ведет к нескольким 1С товарам, статус
  `ambiguous`, а не автоматический выбор первого варианта.

# Data Sources And Boundaries

Разрешено читать:

- WB product cards, sizes and barcodes из collector `wb_product_cards`;
- Ozon product, posting and stock identifiers из existing Ozon snapshots;
- 1С OData: номенклатура, характеристики, штрихкоды, организации и безопасные
  справочные поля;
- локальные ignored mapping files как импорт подтвержденных связей, если строка
  однозначно сопоставляет товар маркетплейса и товар 1С;
- исторические `sku_mapping` snapshots как начальный seed для сервиса.

Запрещено:

- читать или возвращать `.env`, tokens, passwords, API keys, connection strings;
- логировать raw request/response bodies с клиентскими товарами;
- писать во внешние системы;
- скрыто заменять существующий accepted mapping при source refresh;
- подставлять `missing` cost или mapping как ноль.

# Data Model

## `marketplace_mapping_item`

Каноничный товар маркетплейса для сопоставления.

Поля:

- `client_id`;
- `tenant_id`;
- `marketplace`: `wb` или `ozon`;
- `seller_account_id`;
- `organization_id`, если известна по account/org mapping;
- `marketplace_item_key`: стабильный ключ внутри marketplace/provider;
- WB поля: `nm_id`, `vendor_code`, `barcode`, `tech_size`, `chrt_id`;
- Ozon поля: `offer_id`, `product_id`, `sku`, `sku_fbs`, `sku_fbo`, `barcode`;
- справочные поля: `name`, `brand`, `subject`, `category`, `source_snapshot_id`;
- `status`: `active`, `archived`, `excluded`;
- `updated_at`.

## `onec_mapping_item`

Безопасная проекция номенклатуры 1С.

Поля:

- `client_id`;
- `tenant_id`;
- `organization_id`;
- `onec_item_id`;
- `onec_code`;
- `onec_article`;
- `onec_name`;
- `onec_characteristic_id`;
- `onec_characteristic`;
- `barcodes`;
- `source_snapshot_id`;
- `status`: `active`, `archived`;
- `updated_at`.

## `marketplace_1c_mapping_candidate`

Кандидат связи.

Поля:

- `client_id`;
- `marketplace_item_id`;
- `onec_item_id`;
- `method`: `barcode`, `article`, `offer_id`, `sku`, `name`, `imported`,
  `manual_search`, `rule`;
- `confidence`: `0..1`;
- `status`: `candidate`, `needs_review`, `ambiguous`, `rejected`, `accepted`;
- `reason`;
- `source_snapshot_id`;
- `created_at`;
- `updated_at`.

## `marketplace_1c_mapping_decision`

Append-only журнал действий.

Поля:

- `client_id`;
- `marketplace_item_id`;
- `onec_item_id`, если действие относится к конкретному кандидату;
- `action`: `accept`, `auto_accept`, `reject`, `revoke`, `exclude`, `restore`;
- `reason`;
- `created_by`;
- `created_at`;
- `previous_onec_item_id`;
- `previous_status`;
- `previous_method`.

## Current Mapping View

Расчетный слой видит только текущую связь:

- один `marketplace_item_id` может иметь не больше одной текущей accepted-связи;
- один `onec_item_id` может быть связан с несколькими marketplace items;
- если несколько accepted-связей для одного marketplace item невозможны
  технически, дубликат возвращает `409`;
- `excluded` сохраняет причину и не попадает в прибыль как обычный missing.

# API Contract

Все канонические endpoints клиентские: `client_id` обязателен в пути и должен
совпадать с доступным пользователю клиентом. Staff-only endpoints:

- `GET /api/clients/{client_id}/mapping/items` - список marketplace items с
  серверной пагинацией, поиском, фильтрами по marketplace, кабинету,
  организации, статусу и причине;
- `GET /api/clients/{client_id}/mapping/items/{item_id}/candidates` -
  кандидаты 1С для выбранного marketplace item, включая сохраненные кандидаты;
- `GET /api/clients/{client_id}/mapping/onec-search` - поиск 1С номенклатуры по
  названию, артикулу, коду, характеристике и barcode;
- `POST /api/clients/{client_id}/mapping/items/{item_id}/accept` - принять
  `onec_item_id` или выбранного кандидата;
- `POST /api/clients/{client_id}/mapping/items/{item_id}/reject` - отклонить
  кандидата;
- `POST /api/clients/{client_id}/mapping/items/{item_id}/revoke` - снять
  текущую связь;
- `POST /api/clients/{client_id}/mapping/items/{item_id}/exclude` - исключить
  товар из расчета с обязательной причиной;
- `GET /api/clients/{client_id}/mapping/items/{item_id}/history` - история
  решений;
- `POST /api/clients/{client_id}/mapping/rebuild-candidates` - пересчитать
  кандидатов из текущих read-only snapshots и идемпотентно применить
  единственные точные barcode-связи. Ответ содержит `autoAccepted`,
  `remainingReview`, `currentMappingConflictCount`, `affectedReportItems` и
  `reportRebuildRequired`;
- `GET /api/clients/{client_id}/mapping/export/sku-mapping` - безопасный
  экспорт текущего
  `sku_mapping` для расчетчика.

Импорт старых TXT/TSV/CSV файлов остается на endpoint
`POST /api/clients/{client_id}/mapping-file`. Он не возвращает raw содержимое
файла. Если строка файла однозначно находит товар маркетплейса и товар 1С,
сервис создает текущую accepted-связь с методом `imported_mapping_file`. Если
строка неполная, конфликтует с уже принятой ручной связью или не находится в
текущих snapshots, она учитывается как skipped/conflict и остается задачей для
ручной панели.

Клиентская роль получает `403` на write endpoints. Для read endpoints клиентская
роль в MVP видит только агрегированные статусы, если отдельный accepted spec не
разрешит просмотр строк mapping.

# UI Requirements

Первый экран - рабочая таблица, не лендинг.

Основной сценарий:

1. Консультант открывает раздел `Сопоставление`.
2. В левой таблице видит marketplace items с колонками: marketplace, кабинет,
   организация, товар, артикул/offer, barcode, текущий статус, текущая 1С
   номенклатура, причина проблемы.
3. По выбранной строке справа открывается панель кандидатов 1С.
4. Панель показывает сохраненных кандидатов, live search, признаки совпадения,
   confidence и историю.
5. Консультант нажимает `Принять`, `Отклонить`, `Снять` или `Исключить`.
6. UI обновляет строку без перезагрузки и пишет решение в журнал.

Статусы в таблице:

- `Нет пары`;
- `Есть кандидаты`;
- `На проверку`;
- `Неоднозначно`;
- `Сопоставлен вручную`;
- `Сопоставлен авто`;
- `Исключен`;
- `Требует обновления источников`.

Требования к UX:

- по умолчанию открывать очередь аналитика со статусами `needs_review`,
  `ambiguous` и `missing`; нерешенная строка остается в очереди до явного
  ручного решения. Автоматический выбор запрещен для слабых и неоднозначных
  кандидатов, но не для единственного точного штрихкода живой 1С;
- из строки `missing_mapping` или `ambiguous_mapping` отчета давать прямой
  переход к соответствующей карточке очереди без изменения данных;
- показывать способ и уверенность каждого кандидата понятными подписями,
  выделяя наиболее точный вариант только как подсказку, а не как принятое
  решение;
- серверная пагинация и фильтры;
- быстрый поиск по marketplace item и 1С item;
- сохранение фильтров в URL;
- подтверждение перед `revoke` и `exclude`;
- inline ошибки без raw данных;
- счетчики `всего`, `сопоставлено`, `на проверку`, `нет пары`, `исключено`.

# Normalization To `sku_mapping`

`sku_mapping` строится из current mapping view:

- `client_id`, `seller_account_id`, `organization_id` - из marketplace item и
  account/org mapping;
- `marketplace` - внутреннее поле для marketplace-aware расчетов;
- WB: `nm_id`, `vendor_code`, `barcode`;
- Ozon: `offer_id`, `product_id`, `sku`, `sku_fbs`, `sku_fbo`, `barcode`;
- `onec_item_id`, `onec_article`, `onec_characteristic` - из accepted 1С item;
- `match_method`: `mapping_service_manual`, `mapping_service_auto_barcode`,
  `mapping_service_imported`, `mapping_service_excluded`;
- `confidence`: `1` для ручного accept, рассчитанная уверенность для авто;
- `status`: `matched`, `missing`, `ambiguous`, `excluded`;
- `comment`: человекочитаемая причина;
- `updated_by`: пользователь или системный процесс;
- `updated_at`.

Совместимость с `sku_mapping_snapshot` сохраняется: экспорт сервиса формирует
WB-строки `SkuMapping` и Ozon-строки `OzonSkuMapping` с теми же стабильными
идентификаторами, которые ждут текущие расчеты.

Если current mapping отсутствует:

- нет кандидатов -> `missing`;
- несколько разных 1С товаров среди сильных кандидатов -> `ambiguous`; несколько
  методов, указывающих на один и тот же 1С товар, считаются одним кандидатом;
- есть слабый кандидат -> `needs_review` в сервисе и `missing`/`ambiguous` в
  расчетном слое, пока оператор не подтвердит связь;
- товар исключен -> `excluded`.

# Security, Tenant Isolation, Audit, Retention

- Все таблицы содержат `tenant_id` и `client_id`.
- API проверяет роль пользователя и доступ к tenant.
- Write endpoints доступны только `consultant/admin`.
- Decisions append-only; исправление делается новым действием, а не правкой
  старой записи.
- В API и audit нельзя возвращать raw file bodies, `.env`, токены, пароли,
  connection strings или полные клиентские выгрузки.
- Raw import файлы хранятся только в `data/`/source refresh storage и очищаются
  общей retention-политикой.
- Экспорт `sku_mapping` хранит snapshot id и hash, чтобы расчет можно было
  воспроизвести.

# Errors And Edge Cases

- `401 unauthorized`: пользователь не авторизован.
- `403 forbidden`: клиентский пользователь пытается менять mapping или читать
  строки, не разрешенные для его роли.
- `404 item_not_found`: `client_id`, marketplace item, кандидат или 1С item не
  найден либо не принадлежит доступному клиенту.
- `409 already_mapped`: marketplace item уже имеет accepted-связь, сначала
  нужно `revoke`.
- `409 candidate_conflict`: кандидат 1С конфликтует с текущими правилами,
  tenant boundary или устарел после перестроения.
- `422 reason_required`: для `exclude` и `revoke` нужна причина.
- `400`/`413`: импортируемый mapping-файл некорректен или слишком большой.
- Пустой marketplace snapshot не создает пустой successful mapping: refresh
  получает `needs_review`.
- Устаревший mapping source не блокирует чтение старого отчета, но новый отчет
  получает `needs_review` или блокировку по readiness rules.
- Если нет WB/Ozon/1С snapshot, сервис не делает фиктивных связей и не
  подставляет нули.
- Preflight проверяет состояние mapping service и пишет warning для пустого,
  stale или требующего review сервиса; отсутствие старой папки
  `data/onec_marketplace_mapping` больше не является самостоятельным blocker.

# Acceptance Criteria

- Есть accepted DB schema для таблиц marketplace items, 1С items, candidates и
  decisions.
- Staff-only API поддерживает list, candidates, accept, reject, revoke, exclude,
  history и export `sku_mapping`.
- UI позволяет вручную принять, отклонить и снять связь без обращения к 1С на
  запись.
- Любое решение пишет append-only audit row.
- Расчетный `sku_mapping` строится только из current mapping view и fallback
  статусов, а не напрямую из `ИС_Маркетплейс`.
- Source refresh может пересчитать кандидатов из read-only snapshots и не
  перетирает manual accepted decisions.
- Единственный точный barcode-кандидат автоматически становится current mapping
  с методом `mapping_service_auto_barcode`, решением `auto_accept` и audit;
  повторный rebuild не создает дубликатов.
- Если новые auto-связи затрагивают текущий отчет, `onec-only` создает новый
  staff-only draft из защищенного WB-base и свежих 1С/mapping/налогов; current и
  published не переключаются. При отсутствии пригодного WB-base используется
  полный read-only refresh через worker.
- `sku_mapping` SourceLoad конкретного отчета получает `loaded`, если в строках
  этого отчета больше нет mapping-проблем, даже когда общая очередь содержит
  товары без продаж.
- Для legacy Excel-контура старый файл используется только как набор точных
  `nm_id`/barcode alias. Решения `mapping_service_auto_barcode`, manual и
  excluded переопределяют товар для всех его alias; проекция
  `imported_mapping_file` не заменяет более точную исходную строку того же
  файла. Налоговые профили и current mapping передаются builder-у из PostgreSQL.
- Старые TXT/TSV/CSV и 1С extension responses принимают однозначные связи как
  current mapping, а конфликтные строки оставляют для ручной проверки.
- Отчет явно показывает `missing_mapping`, `ambiguous_mapping` и `excluded`.
- Тесты и docs validators проходят.

# Test Plan

- Contract tests для схемы `marketplace_mapping_item`, `onec_mapping_item`,
  candidate и decision.
- API tests: tenant access, staff-only writes, list filters, candidate search,
  accept, reject, revoke, exclude, history, `409` conflicts.
- Mapping tests: exact unique barcode auto-accept, multiple barcode candidates,
  weak article, missing candidate, rejected candidate, excluded item,
  idempotency, audit, existing mapping priority and conflict counter.
- Source refresh tests: rebuild candidates does not overwrite manual accepted
  decisions; stale mapping health is visible.
- Report tests: `sku_mapping` export feeds existing calculation and preserves
  `missing_mapping`, `ambiguous_mapping`, `excluded`.
- Security tests: API responses do not contain tokens, passwords, `.env`,
  connection strings or raw imported files.
- UI smoke tests: page loads, filters work, accept/revoke updates visible row.

# Implementation And Rollout

1. DB schema и ORM models добавлены.
2. Staff-only API и tests добавлены.
3. `sku_mapping` export и source refresh rebuild подключены.
4. UI-панель сопоставления добавлена в существующий vanilla JS/CSS кабинет.
5. Импортировать текущий файловый/1С mapping как подтвержденные связи, а
   skipped/conflict строки оставить в ручной очереди.
6. Пересобрать отчет и сверить проблемные строки.

# Rollback

- Отключить UI/API write endpoints feature flag.
- Использовать последний approved `sku_mapping` snapshot для расчетов.
- Вернуться к manual TXT/TSV/CSV upload как emergency import без записи во
  внешние системы.

# Changelog

- 2026-07-08 - accepted own marketplace/1C mapping service as the new source of
  truth for `sku_mapping`; file/1С marketplace extension import is supported as
  bulk accepted mapping for unambiguous rows and manual queue input for the
  remainder.
- 2026-07-08 - implemented DB models, FastAPI endpoints, source refresh rebuild,
  preflight health check, vanilla JS/CSS UI and tests; canonical API paths are
  client-scoped under `/api/clients/{client_id}/mapping/...`.
- 2026-07-10 - made unresolved marketplace/1C links an explicit analyst queue,
  added direct navigation from Ozon problem rows and kept every candidate
  selection manual and auditable.
- 2026-07-11 - accepted system `auto_accept` for the only exact barcode from
  live read-only 1C, protected existing accepted mappings, added conflict and
  report-impact counters, and kept all weaker/ambiguous candidates manual.
