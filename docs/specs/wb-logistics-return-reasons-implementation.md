---
spec_id: "workspace-shumeyko-partners-wb-logistics-return-reasons-implementation"
title: "WB: причины возвратов (goods-return и claims)"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "consultant"]
source_of_truth: false
related_code: [scripts/probe_wb_logistics_factors.py, src/wb_unit_economics/wb_finance.py, src/wb_unit_economics/wb_goods_return.py, src/wb_unit_economics/logistics_analysis.py, src/wb_unit_economics/web/source_refresh.py, src/wb_unit_economics/web/repository.py, src/wb_unit_economics/web/app.py, src/wb_unit_economics/web/settings.py, sql/postgres_schema.sql]
related_tests: [tests/test_probe_wb_logistics_factors.py, tests/test_wb_finance.py, tests/test_wb_goods_return.py, tests/test_logistics_analysis.py, tests/test_source_refresh.py, tests/test_web_app.py]
contracts: [wb_api_snapshot, unit_economics_report, ai_analysis_summary]
ai_sections:
  status: "Статус документа"
  goal: "Цель"
  scope: "Scope"
  sources: "Источники и границы чтения"
  probe: "Техническая проверка доступности источников"
  calculation: "Модель связывания и покрытия"
  marts: "Расчётные витрины"
  api: "API"
  interface: "Интерфейс"
  acceptance: "Acceptance Criteria"
  tests: "Test Plan"
depends_on: [workspace-shumeyko-partners-wb-logistics-cost-analysis-implementation]
rollout_required: true
updated_at: "2026-07-22"
---

# Статус документа

Статус — `accepted`. Это подчинённый implementation-spec внутри truth_scope
`logistics-cost-analysis`. Канонический документ scope — accepted
[`docs/specs/wb-logistics-cost-analysis-implementation.md`](wb-logistics-cost-analysis-implementation.md)
(`truth_priority: 100`); при любом расхождении действует он. Спек не является
источником истины (`source_of_truth: false`) и не меняет формулы, классификацию,
финансовый gate первой очереди или границу факт/оценка/гипотеза.

Назначение спека — закрепить ДО end-to-end кода отдельный read-only слой причин
возвратов покупателя и его связывание с уже готовым фактом возврата из Finance.
Ключевое ограничение канона: Finance подтверждает ФАКТ и СУММУ возврата, но не
причину покупателя; интерфейс не придумывает причину. Этот spec описывает, как
безопасно добавить причину там, где отдельный WB-источник её действительно
содержит, и как честно показывать её отсутствие.

Решения приняты 22 июля 2026 года после повторной построчной сверки текущего
официального WB OpenAPI. Первый безопасный R-0I fail closed на storage
ambiguity, а read-only R-0L не нашёл пригодного прежнего lineage. После
отдельно разрешённого нового immutable draft повторный R-0I подтвердил exact
goods-return crosswalk `srid → Finance.srid` и однозначную canonical return
chain. Claims source keys в текущем окне отсутствуют, поэтому общий identity и
implementation gate остаются закрыты. R-1 требует отдельного accepted-решения
об изменении контракта, R-2 — собственного положительного identity evidence;
этот статус не подтверждает реализацию, client enable или rollout.

# Текущее состояние реализации

Первая очередь (`wb-logistics-v5`) считает обратную логистику и суммы возвратов
из Finance, но НЕ содержит причину возврата и корректно пишет `Причина
недоступна в Finance`.

В `main` уже есть предварительный read-only `goods-return` client/flatten/export
и файловый вызов из full/weekly source refresh. Это prework, а не завершённый
источник: коллекция не зарегистрирована как авторитетный snapshot, нет
lineage/context/mart/API/UI и нет связывания с Finance. `claims` connector
отсутствует. Живой probe 19 июля подтвердил доступ и ожидаемые имена полей
`goods-return` только для разрешённых token scopes; claims доступен не для
каждого scope.

Первичный R-0 выполнен 22 июля 2026 года после принятия спека. Source schema
gate пройден, но direct Finance/source join не подтвердился даже на
максимальном 31-дневном goods-return window, выровненном по последнему
immutable report. Этот результат обосновал R-0I; он не разрешал R-1…R-5 и не
разрешает использовать `nm_id`, `srid` или `orderId` отдельно как обход.

Первый R-0I также выполнен 22 июля. Внешний source gate и выравнивание окна
прошли, но выбранный Finance lineage одновременно был представлен DB-строками
и `file_authoritative` коллекцией. Production selector классифицировал это как
`source_storage_ambiguity`; сравнение не принималось до нового unambiguous
verified snapshot.

R-0L выполнен в тот же день без внешних API-вызовов. Newest-first проверка
существующих immutable reports нашла report candidates и Finance return fact,
но не нашла ни одного verified unambiguous return lineage. Зафиксированы
`sourceIntegrityFailurePresent=true`, `databaseFileAmbiguityPresent=true` и
`newReportRequired=true`; автоматическое переиспользование прежнего report не
разрешено, `implementationGate=false`.

После отдельного operational-разрешения и backup выполнен production full
source refresh из ревизии `e0d6578`. Создан новый draft с
`publicationStatus=draft`, `isCurrent=false`: Finance collection загружена как
verified file-authoritative (`rowPersistence=skipped_large_snapshot`), DB-строк
для неё нет, ambiguity отсутствует, logistics context имеет `ready`. Повторный
R-0I подтвердил `goodsReturnIdentityGate=true` для exact
`goods-return.srid → Finance.srid`; canonical return chain разрешается
однозначно, baseline `srid → orderUid` не совпал. Claims source keys в текущем
окне отсутствуют, поэтому `claimsIdentityGate=false`,
`completeIdentityGate=false`, `contractChangeRequired=true` и
`implementationGate=false`. Production health остался `ok`, опубликованный
current report, runtime и client flags не изменены.

# Цель

Дать по возврату, где это подтверждено отдельным WB-источником, причину или
комментарий покупателя, строго разделяя:

- `Причина подтверждена` — получена из отдельного read-only источника WB;
- `Причина — гипотеза` — возможное объяснение для ручной проверки, не факт;
- `Причина недоступна` — источник не покрывает этот возврат/период.

Причина возврата усиливает рекомендации по обратной логистике из канона, но
никогда не превращает гипотезу в установленный факт и не меняет финансовый
расчёт.

# Термины и обязательные трактовки

Термины первой очереди наследуются. Дополнительно:

- `Факт возврата` — финансовый факт и сумма из Finance (как в первой очереди).
- `Причина возврата продавцу` — поле `reason` из отчёта `goods-return`. Описывает
  возврат/перемещение товара продавцу, а НЕ универсальную причину каждого
  финансового возврата.
- `Заявка покупателя` — запись `claims` с `user_comment` (комментарий
  покупателя) и `wb_comment`. Ограничена недавним окном.
- `Return join key` — точный `(wb_cabinet_id, srid, nm_id)`. `srid` или `nm_id`
  отдельно, совпадение в другом кабинете и order-only fallback не являются
  достаточной связью.
- `Персональные/чувствительные данные` — `user_comment`, `origin_id_info`, фото,
  видео и иные вложения заявки. Они остаются только в защищённом raw snapshot;
  в mart/API/AI переносится только безопасный признак наличия комментария.

`goods-return.reason` и `claims.user_comment` НЕ взаимозаменяемы: это разные
сущности с разными окнами и охватом. Их нельзя объединять в один «истинный»
столбец причины.

# Scope

## В scope

- read-only коннекторы `goods-return` и `claims` с сохранением raw snapshot до
  нормализации и отдельными source identities;
- связывание причины с фактом возврата только по точному return join key без
  дублирования сумм;
- явные статусы покрытия: `подтверждена` / `гипотеза` / `недоступна`, включая
  `unmatched` (причина есть, а факта в срезе нет — и наоборот);
- витрина покрытия причин на уровне товара/возврата;
- дополнение блока «Возвраты»/рекомендаций причиной там, где она подтверждена;
- безопасная обработка персональных данных покупателя (агрегация/обезличивание).

## Out Of Scope

Наследует Out Of Scope канона. Дополнительно вне scope:

- любые write-методы, включая ответ покупателю `PATCH returns-api /api/v1/claim`;
- трактовка `goods-return.reason` как причины каждого финансового возврата;
- смешивание `reason` и `user_comment` в единый столбец;
- перенос дословных комментариев, `origin_id_info`, фото, видео или ссылок на
  вложения в mart, API, UI или AI;
- изменение финансового факта или суммы возврата из-за наличия/отсутствия
  причины;
- восстановление причины за исторический период, который источник не покрывает;
- автоматическая генерация или сохранение гипотезы как source fact.

# Источники и границы чтения

Оба метода read-only, вызываются токенами минимально необходимых категорий.
Пути, параметры, поля примеров и лимиты повторно сверены 22 июля 2026 года по
текущему официальному WB OpenAPI. Live probe всё равно обязан fail closed при
расхождении фактической envelope/schema.

## Возвраты продавцу — `goods-return`

- `GET https://seller-analytics-api.wildberries.ru/api/v1/analytics/goods-return`
  (токен «Аналитика»).
- Поля: `reason` (причина), `status`, `returnType`, `srid`, `nmId`, `barcode`,
  `orderId`.
- Envelope: объект с массивом `report`; другой тип или отсутствие ожидаемой
  envelope — `schema_mismatch`, а не пустой успешный snapshot.
- Ограничения: обязательные `dateFrom`/`dateTo` (`YYYY-MM-DD`), максимум
  **31 день** за запрос; лимит **1 запрос/мин**, burst 10. Официальный контракт
  не обещает глубину истории, поэтому её определяет только live probe.
- Описывает возврат/перемещение товара продавцу, не универсальную причину.

## Заявки покупателей — `claims`

- `GET https://returns-api.wildberries.ru/api/v1/claims` (токен «Возвраты
  покупателями»).
- Обязательный параметр `is_archive` — **boolean** (`false` — на рассмотрении,
  `true` — в архиве); без него ответ 400. Legacy-описание типа string больше не
  является контрактом.
- Pagination: `limit` от 1 до 200 (default 50), `offset >= 0`, provider `total`;
  active и archive собираются раздельно до точной сверки `total`.
- Поля: `id`, `claim_type`, `status`, `nm_id`, `user_comment`, `wb_comment`,
  `srid`, `dt`, `order_dt`, `actions`, `origin_id_info`, фото и видео.
- Окно метода — текущие **14 дней**. `is_archive=true` выбирает статус заявки,
  но не является документированным глубоким историческим архивом. Лимит для
  personal/service token — **20 запросов/мин**.
- `PATCH /api/v1/claim` (ответ покупателю) — write, в read-only контур не
  входит.

## Read-only boundary

Новые write-методы запрещены. Разные rate limits (goods-return 1/мин; claims
20/мин) требуют раздельного бюджета запросов и ограниченного backoff на HTTP
429. HTTP 401/402/403 считается недоступным scope, а не пустым результатом. Raw
snapshot сохраняется до нормализации в tenant/cabinet scope; чувствительные
поля не копируются в Git, Markdown, логи, mart, API или AI.

# Техническая проверка доступности источников

До R-1…R-5 на авторизованном read-only контуре без публикации raw подтвердить
по каждому кабинету и каждому source slice один из безопасных статусов:
`confirmed_empty`, `confirmed_nonempty`, `access_denied`,
`paid_scope_required`, `unavailable`, `schema_mismatch` или
`pagination_mismatch`.

Probe-чеклист:

1. Проверить доступ token scope «Аналитика» для `goods-return` и «Возвраты
   покупателями» для `claims`; другой сохранённый токен не использовать как
   молчаливый fallback.
2. `goods-return`: минимальный GET одного окна до 31 дня; проверить object /
   `report` envelope и имена `reason`, `srid`, `nmId`, `status`, `returnType`
   без вывода значений.
3. `claims`: отдельные GET для `is_archive=false` и `is_archive=true` с
   `limit=1`, `offset=0`; проверить `claims`/`total` и имена `id`, `nm_id`,
   `srid`, `user_comment`, `dt` без вывода значений.
4. При доступе выполнить локальную полную pagination и зафиксировать только
   boolean reconciliation с provider total; total/count не переносить в
   Markdown или вывод probe.
5. На сохранённом защищённом snapshot локально проверить exact
   `(cabinet, srid, nm_id)` join к Finance и только boolean наличия matched и
   unmatched в обе стороны. Goods-return window выровнять по `period_end`
   выбранного immutable report run; конкретный период, денежные суммы и
   identifiers не выводить.
6. Проверить, что в flat/mart projection отсутствуют `user_comment`,
   `wb_comment`, `origin_id_info`, media paths и другие raw значения; допустим
   только `has_user_comment`.

Результат — boolean-only матрица доступности без provider labels, counts,
периодов клиентской активности, идентификаторов, причин и комментариев. Она
определяет, какие подпакеты можно начать. R-1…R-5 разблокируются только после
хотя бы одного доказанного exact match на согласованном source/report window;
одна лишь доступность schema недостаточна. Недоступный или частичный источник
не заполняется гипотезой и не блокирует основную логистику.

## R-0 live evidence — 22 июля 2026 года

Официальные Reports и Customer Communication OpenAPI повторно проверены до
probe. Test service environment не содержит usable WB integration, поэтому
внешних запросов из test не выполнялось. Отдельный transient probe через
production service environment выполнил только разрешённые GET и не менял
production process, БД или configuration.

Boolean-only evidence подтвердил:

- goods-return и обе claims envelope/schema доступны хотя бы на одном
  разрешённом token scope; schema mismatch, paid-scope error и unavailable не
  обнаружены;
- goods-return имеет непустой ответ; claims active/archive на доступном scope
  пусты, а на другом scope возвращают access denied;
- report window выровнен, source и Finance return keys присутствуют, invalid
  source keys отсутствуют;
- exact `(cabinet, srid, nm_id)` match не найден, unmatched присутствует в обе
  стороны; `joinGate=false`, итоговый `implementationGate=false`.

В evidence не переносились provider labels, counts, периоды клиентской
активности, identifiers, причины, комментарии, media или суммы. Результат не
разрешает R-1…R-5 и не влияет на основную логистику, отчёты или feature flags.

## R-0I identity crosswalk contract

R-0 показал, что canonical Finance chain использует `orderUid`, а прямое
сравнение source `srid` с этим полем не доказано. Актуальный Finance OpenAPI
возвращает `orderUid`, `srid` и `orderId` как разные поля; goods-return также
возвращает `srid` и `orderId`, причём `orderId` документирован как номер
сборочного задания. Поэтому равенство разных полей не предполагается.

R-0I выполняется на том же выровненном goods-return window и на Finance rows из
последнего подходящего immutable report с неблокирующим logistics context
(`current → base → contributor`). Диагностика читает только базовые колонки,
доступные до factor migrations, но не ослабляет production selector. DB и
`file_authoritative` проходят тем же selector/integrity contract, что основная
логистика. Scope/hash/revision/path/storage ambiguity закрывает identity gate.

Разрешены только следующие кандидаты с обязательными
`(tenant, client, wb_cabinet_id, nm_id)` dimensions:

- baseline `source.srid → Finance.orderUid` — только для подтверждения причины
  прежнего R-0 failure, не как новый контракт;
- `goods-return.srid → Finance.srid`;
- `goods-return.orderId → Finance.orderId`;
- `claims.srid → Finance.srid`; прямой claims → `orderUid` остаётся baseline.

Same-name match должен однозначно разрешаться в один существующий canonical
Finance `chain_key` с return fact. Несколько canonical chain для одного
candidate key, конфликт source identity, другой кабинет, несовпадающий `nm_id`
или неполный ключ дают `ambiguous/unmatched`, а не fallback. Совпадение только
по товару, дате, `stickerId`, `shkId` либо любому одиночному identifier
запрещено.

Вывод `--mode r0-identity` содержит только boolean-признаки presence,
matched/unmatched, ambiguity, verified lineage и отдельные gates для
goods-return и claims. Fail-closed диагностика отдельно различает metadata,
schema compatibility, selector contract, payload/hash/identity/revision/scope
и DB/file storage failures, но публикует их только как booleans. Она не печатает
names, counts, периоды, identifiers, hashes, причины, комментарии, media, суммы
или raw rows. Даже положительный candidate не меняет production join
автоматически: R-0I обновляет accepted решение отдельно, после чего разрешается
только соответствующий R-1 или R-2.

## R-0I live evidence — 22 июля 2026 года

Test service environment не содержал usable WB integration; внешний запрос из
него не выполнялся. Transient production-service process выполнил только
read-only GET и чтение уже сохранённого lineage; service, БД, configuration и
feature flags не менялись.

Boolean-only evidence подтвердил доступность внешней source schema и
выровненное report window. Exact candidate evaluation остановлен до join:
production selector обнаружил DB/file storage ambiguity у Finance snapshot.
`verifiedLineagePresent=false`, `databaseFileAmbiguityPresent=true`,
`goodsReturnIdentityGate=false`, `claimsIdentityGate=false` и
`completeIdentityGate=false`. В evidence не перенесены provider labels, counts,
периоды клиентской активности, identifiers, причины, комментарии, media, суммы,
paths, hashes или raw rows.

Этот первый проход обосновал новый immutable report. Изменять опубликованный
report или вручную выбирать одну из конфликтующих DB/file копий запрещено.

После отдельно разрешённого full source refresh повторный проход на новом
draft подтвердил `completeSourceGate=true`, `reportWindowAligned=true` и
verified lineage без DB/file ambiguity. Exact
`goods-return.srid → Finance.srid` имеет match и однозначно разрешается в
canonical return chain; `goodsReturnIdentityGate=true`. Baseline
`goods-return.srid → Finance.orderUid` не совпал. В claims current window source
keys отсутствуют, поэтому `claimsIdentityGate=false` и
`completeIdentityGate=false`. Положительный goods-return candidate не меняет
accepted join автоматически: `contractChangeRequired=true`, общий
`implementationGate=false`; R-1 требует отдельного accepted-решения, R-2 —
положительного claims gate.

Новый draft не опубликован и не стал current. Production/client flags не
менялись; evidence осталось boolean-only без labels, counts, клиентских окон,
identifiers, причин, комментариев, media, сумм, paths, hashes и raw rows.

## R-0L existing lineage discovery contract

Перед созданием нового report разрешён отдельный read-only R-0L preflight. Он
не обращается к WB API и не изменяет БД/файлы: для каждого разрешённого scope
перебирает существующие immutable reports newest-first и повторно проверяет их
Finance lineage тем же production selector. Report с DB/file ambiguity,
metadata/scope/hash/revision/path failure или без Finance return fact не может
считаться подходящим и не выбирается автоматически.

`--mode r0-lineage` публикует только boolean-признаки: наличие report
candidate, verified unambiguous return lineage, database-only/file-only
storage, ambiguity/integrity/schema/selector failure и `newReportRequired`.
Идентификаторы, число reports/rows, периоды, paths, hashes, суммы и raw rows не
выводятся. Даже найденный старый verified report не меняет R-0I window сам:
его применение требует отдельного accepted решения с явным выравниванием
source window. Если verified candidate отсутствует, новый immutable report
обязателен; R-0L сам его не создаёт.

## R-0L live evidence — 22 июля 2026 года

Test service environment не содержал usable WB integration и корректно вернул
закрытый результат без внешних запросов. Transient production-service process
не обращался к WB API и только read-only перебрал metadata и Finance lineage
существующих immutable reports. Production service, БД, файлы, configuration,
reports и feature flags не менялись.

Boolean-only evidence подтвердил наличие report candidate и Finance return
fact, но не подтвердил verified lineage ни в database-only, ни в file-only
storage. Production selector обнаружил source integrity failure и DB/file
ambiguity; `verifiedUnambiguousReturnLineagePresent=false`,
`newReportRequired=true`, `acceptedReuseDecisionRequired=false` и
`implementationGate=false`.

В evidence не переносились provider labels, counts, клиентские периоды,
identifiers, причины, комментарии, media, суммы, paths, hashes или raw rows.
Следующий допустимый data-шаг — новый immutable report из однозначного verified
Finance storage. R-0L не разрешает ради этого применять production migrations,
менять runtime, удалять одну из копий storage или модифицировать опубликованный
report: такие операции требуют отдельного rollout/retention решения и своих
предусловий.

# Модель связывания и покрытия

- Факт и сумма возврата берутся ТОЛЬКО из Finance (первая очередь); причина —
  дополнительный слой, не меняющий сумму.
- Source identity связывается с canonical Finance chain только через принятый
  exact same-name crosswalk в scope `(tenant, client, cabinet, nm_id)`.
  Неполный ключ, совпадение в другом кабинете или несколько canonical chain
  дают явный `unmatched`/`conflicting`, а не fallback или случайный выбор.
- Непустой `goods-return.reason` становится `evidenceType=fact` только после
  exact join. Отсутствие источника/окна/join — `data_unavailable`.
- `claims.user_comment` не переносится как текст и не подменяет reason. Exact
  claim даёт только `claimAvailable=true` и `hasUserComment=true|false`; это
  факт наличия заявки/комментария, а не автоматически нормализованная причина.
- `hypothesis` допустим только как отдельно маркированная детерминированная
  рекомендация для ручной проверки. В первой версии hypothesis не сохраняется
  в source mart и не показывается рядом с подтверждённой причиной как равная ей.
- Покрытие считается отдельно для Finance→goods-return, Finance→claims и
  unmatched в обратную сторону; UX показывает `причина получена` и `причина
  недоступна` по полному фильтрованному срезу.
- Историю объясняют только данными периода, который источник покрывает; вне окна
  — `data_unavailable`.

# Расчётные витрины

Additive, неизменяемые, с lineage до `report_run`, версий и hash входов. Старый
отчёт без них — `needs_rebuild`, на лету не достраивается.

Добавляются `report_logistics_return_reason_contexts` и
`ReportRun.logistics_return_reasons_required`. Context хранит методику
`wb-logistics-return-reasons-v1`, statuses двух sources, input/snapshot hashes,
coverage windows, safe coverage counters, row-count reconciliation и только
безопасные blocking/review codes. Авторитетный snapshot выбирается отдельно для
`wb_goods_return` и `wb_return_claims` по lineage `primary → base → contributor`;
peer conflict одного приоритета, hash/manifest/row-count/path/tenant mismatch и
DB/file ambiguity блокируют только F-5.

## `report_logistics_return_reason_rows`

Гранулярность — Finance-return/chain в срезе отчёта. Одна строка на
`(tenant, client, cabinet, company, scheme, chain_key, product_ref)` без fanout.
Поля: `product_ref`, обезличенный `chain_key`, дата финансового возврата,
`reason_category`, `reason_source`, `evidence_type`, `match_status`,
`claim_available`, `has_user_comment`, source hash digests и row hash. Raw
`srid`, `nm_id`, claim ID, комментарии, device data и media paths не хранятся.

Context и rows сохраняются атомарно только при создании нового immutable draft.
Integrity/scope/reconciliation failure создаёт `blocked` context без mart rows
и non-overridable publication blocker, если context required. Недоступный
source/window и unmatched дают `partial/data_unavailable`, но сами по себе не
блокируют публикацию. Опубликованный report run изменять запрещено.

# API

Добавляется read-only
`GET /api/reports/{report_id}/logistics/return-reasons`. Фильтры:
`periodStart`, `periodEnd`, `wbCabinetId`, `clientCompanyId`, `scheme`,
`product`, `reasonSource`, `evidenceType`, `matchStatus`; SQL-pagination
`offset/limit`; сортировки `eventDate`, `product`, `reasonCategory`,
`evidenceType`, `matchStatus`.

Ответ: `dataStatus`, `sliceStatus`, `methodologyVersion`,
`factorMethodologyVersion`, `generatedAt`, source coverage windows,
`filterContext`, coverage полного фильтрованного среза, `rows`, `total`,
`offset`, `limit`, `recommendations`. Raw/hash identifiers и дословные
чувствительные поля не возвращаются. Состояния: старый/устаревший context —
`needs_rebuild`; integrity/scope failure — `blocked`; разрешённый срез без
Finance-возвратов — `empty`; неполный source/join — `partial`; полное покрытие —
`ready`.

Флаги по умолчанию выключены:
`SHUMEYKO_LOGISTICS_RETURN_REASONS_ENABLED` и
`SHUMEYKO_LOGISTICS_RETURN_REASONS_CLIENT_ENABLED`. Staff требует logistics,
factors и return-reasons master; client дополнительно требует все client flags.
При запрете API отвечает 404. Ошибка F-5 не ломает основную логистику.

# Интерфейс

Блок «Факторы стоимости → Причины возвратов» встраивается в существующий
`#tables/logistics` после F-4 и до рейтинга товаров, не создавая отдельного
пункта меню. До frontend-кода готовится синтетический visual target на текущих
токенах кабинета.

- Для каждого возврата показывается статус причины: `Причина подтверждена`,
  `Причина — гипотеза` или `Причина недоступна`; отдельно — доли покрытия
  `причина получена` / `причина недоступна`.
- Подтверждённая причина помечается `Факт`; гипотезы (качество фото, размер,
  несоответствие ожиданиям) показываются только как гипотезы для ручной
  проверки и никогда как установленная причина.
- Дословный комментарий, device data, фото и видео не показываются ни staff, ни
  client через этот интерфейс; доступен только факт наличия заявки/комментария.
- При отсутствии источника сохраняется формулировка канона `Причина недоступна
  в Finance` / `Причина недоступна`.
- Показываются coverage, товар, дата финансового возврата, подтверждённая
  категория goods-return, наличие заявки/комментария и match status. Raw IDs и
  hashes скрыты. На mobile строки превращаются в подписанные карточки.
- Поддерживаются `ready`/`partial`/`empty`/`needs_rebuild`/`blocked`/локальный
  `error`; выключенный флаг скрывает секцию и предотвращает запрос.

# Правила рекомендаций

Наследуют формат канона. Добавляется:

- высокая доля обратной логистики + подтверждённая причина → показать причину и
  действие (`evidenceType=fact`);
- высокая доля обратной логистики без подтверждённой причины → рекомендация
  проверить причины по доступным данным с пометкой ограничения;
- низкое покрытие причин → сначала восстановить/подключить источник, а не делать
  вывод.

Лидеры выбираются SQL по полному фильтрованному срезу.

# AI Boundary

Наследует канонический AI Boundary. AI получает только обезличенные агрегаты
причин и evidence-поля; не читает дословные персональные комментарии и вложения,
не придумывает причину возврата, не выдаёт гипотезу за факт, не смешивает
`goods-return.reason` и `claims.user_comment`.

# Ошибки и пограничные случаи

- `srid`/`nm_id` отсутствует, exact key не сопоставился или дал несколько
  кандидатов → `unmatched`/`conflicting`; сумма возврата остаётся фактом Finance,
  причина `data_unavailable`.
- Причина есть, а факта в срезе нет → отдельный `unmatched`, не влияет на
  денежный итог.
- Возврат вне фактически подтверждённого окна goods-return или текущих 14 дней
  claims → `data_unavailable`, история не досочиняется. `is_archive=true` не
  трактуется как глубокая история.
- `claims` без `is_archive` → ошибка запроса обрабатывается, не блокирует расчёт
  логистики.
- Разные rate limits → backoff на 429, частичный сбор помечается `partial`.
- Пустой `reason` → причина `data_unavailable`; пустой `user_comment` даёт
  `hasUserComment=false`, но не меняет goods-return reason.
- Чувствительные поля не маскируются эвристически в mart: они полностью
  исключаются из flat/mart/API/AI projection.

# Безопасность и tenant isolation

- Каждый запрос ограничен tenant/client/cabinet доступами пользователя.
- Внешние интеграции read-only; `PATCH /api/v1/claim` и любые ответы покупателю
  запрещены.
- Чувствительные данные не попадают в Git, Markdown, логи, flat snapshot,
  открытый API, AI и mart; сохраняется только защищённый raw snapshot и
  безопасные boolean/digest projections.
- Raw snapshot claims сохраняется в действующем защищённом source storage по
  общей retention policy для воспроизводимости; отдельное увеличение retention
  и копирование в immutable runtime запрещены. Raw `srid` не раскрывается через
  F-5 API.

# Этапы реализации

1. `R-0 Probe доступности` — boolean-only матрица goods-return и claims на
   реальном снимке; выполнен, direct source `srid → Finance.orderUid` не доказан.
2. `R-0I Identity crosswalk` — после нового unambiguous draft подтверждён
   goods-return `srid → Finance.srid`; claims и complete gates закрыты, join не
   изменён автоматически, требуется отдельное accepted-решение.
3. `R-0L Existing lineage discovery` — read-only поиск уже существующего
   verified unambiguous return lineage до нового report; выполнен с
   `newReportRequired=true`, сам ничего не создавал.
4. `R-1 goods-return` — только после отдельного accepted-решения довести
   существующий prework до зарегистрированного raw snapshot, selector,
   нормализации `reason`, exact join и статусов покрытия.
5. `R-2 claims` — коннектор active/archive, безопасная обработка PII, признак
   наличия комментария без переноса текста из raw; до положительного claims
   identity evidence не начинается.
6. `R-3 Витрина и API` — `report_logistics_return_reason_rows`, покрытие в ответе
   «Возвраты».
7. `R-4 UI и рекомендации` — статусы причины, доли покрытия, усиление
   рекомендаций обратной логистики.
8. `R-5 Приёмка и rollout` — staff-only за флагом, затем отдельное решение о
   клиентском включении.

Каждый подпакет — за выключенным флагом и additive-миграцией схемы.

# Acceptance Criteria

Design-часть принята 22 июля 2026 года. Реализация готова, когда:

Первый критерий подтверждён для goods-return на новом draft, но не для claims;
остальные критерии реализации ещё не выполнены.

1. probe зафиксировал schema и хотя бы один однозначный same-name
   Finance/source crosswalk в обезличенной boolean-only матрице;
2. факт и сумма возврата остаются из Finance и не меняются наличием причины;
3. `reason` хранится как отдельный source fact; raw `user_comment` не попадает в
   mart/API/AI, сохраняется только `has_user_comment`;
4. каждая причина имеет `evidenceType`; отсутствие покрытия — `data_unavailable`,
   не пустая строка и не гипотеза;
5. `unmatched` в обе стороны показан явно и не искажает денежный итог;
6. чувствительные данные не попадают staff/client API, mart, AI, Git, Markdown
   или логи;
7. история вне окна источника не досочиняется;
8. пользователь одного tenant не получает данные другого;
9. старый отчёт без витрины причин возвращает `needs_rebuild`;
10. ни один сценарий не выполняет запись во внешнюю систему;
11. context+rows атомарны, published run immutable, а row-count/source
    reconciliation fail closed;
12. role/flag matrix возвращает 404 при запрете и не ломает основную логистику.

# Test Plan

- unit: нормализация `reason`; `user_comment` преобразуется только в boolean
  presence до flat/mart projection;
- unit: exact `(cabinet, srid, nm_id)` join, peer conflict и изоляция одинаковых
  идентификаторов между кабинетами;
- unit: claims boolean `is_archive`, limit/offset pagination и provider-total
  reconciliation; окно вне покрытия → `data_unavailable`;
- unit: запрет чувствительных полей в flat/mart/API/AI и стабильность hashes;
- R-0: boolean-only output без labels, counts, IDs, периодов клиентской
  активности и raw values для empty/nonempty/denied/402/429/schema mismatch;
- R-0I: same-name `srid↔srid`/`orderId↔orderId`, canonical-chain resolution,
  кабинетная изоляция, incomplete key, source/canonical ambiguity, pre-factor
  schema compatibility, DB/file ambiguity, transaction isolation и запрет raw;
- R-0L: newest-first immutable report scan, production selector reuse,
  database-only/file-only classification, return-fact requirement, отсутствие
  автоматического выбора и boolean-only output;
- integration: сборка `report_logistics_return_reason_rows` из обезличенного
  снимка, lineage и hash; сумма Finance не меняется;
- source integration: DB/file parity, primary/base precedence, manifest/hash/
  row-count/path/tenant mismatch и storage ambiguity;
- persistence: atomic context+rows, published immutability, required-context
  publication blocker только для missing/outdated/blocked;
- API: покрытие причин и факт/гипотеза/недоступно в ответе «Возвраты»; пустой
  срез → `empty`; старый отчёт → `needs_rebuild`; SQL filters/sorting/pagination
  и coverage полного среза;
- API: role/flag matrix, tenant isolation, отсутствие raw/hash/PII;
- UI: reset при смене report/filter, все состояния, mobile cards, отсутствие
  запроса при выключенном flag и отсутствие трактовки claim comment как reason;
- tenant isolation: недоступность чужих tenant/cabinet;
- rate limit/429: частичный сбор → `partial`, а не тихое обрезание;
- fixtures обезличенные; реальные комментарии/идентификаторы в тесты и
  документацию не переносятся.

Файлы (расширяются существующие): `tests/test_probe_wb_logistics_factors.py`,
`tests/test_wb_goods_return.py`, `tests/test_wb_finance.py`,
`tests/test_logistics_analysis.py`, `tests/test_source_refresh.py`,
`tests/test_web_app.py`; claims получает отдельный test module вместе с
коннектором.

# Rollout And Rollback

1. Выполнить R-0 probe в авторизованном read-only service environment без
   публикации raw и без изменения среды.
2. R-0I и R-0L выполнены; после отрицательного R-0L отдельно разрешённый новый
   immutable draft создан без ручного выбора или удаления DB/file копии.
3. Перед сборкой покрытия goods-return принять отдельное изменение контракта
   по подтверждённому `srid → Finance.srid`. Claims не включать до собственного
   положительного identity gate.
4. Включить причину consultant/admin за отдельным feature flag без клиентской
   публикации.
5. После приёмки — отдельное решение о клиентском включении с проверкой
   обработки персональных данных.

Rollback отключает новые маршруты и блок причины, не меняя существующие отчёты,
финансовый факт и первую очередь. Витрина additive и неизменяема. Внешние
источники при rollout/rollback не изменяются.

# Согласованные решения

1. Причина — отдельный read-only слой поверх Finance; сумма и факт возврата не
   меняются.
2. `goods-return.reason` — отдельный source fact; из claims в mart/API попадают
   только `claimAvailable` и `hasUserComment`, текст не переносится.
3. Чувствительные поля исключаются из flat/mart/API/UI/AI, а не маскируются
   эвристически.
4. Отсутствие покрытия — явный `data_unavailable`, а не пустая строка.
5. `unmatched` в обе стороны показывается явно.
6. Ответы покупателю (`PATCH /api/v1/claim`) остаются вне scope.
7. Join только по `(cabinet, srid, nm_id)`; одиночные поля и order fallback
   запрещены.
8. `claims.is_archive` — boolean; обе выборки ограничены документированными
   текущими 14 днями, глубокая история не предполагается.

# Открытые вопросы

- Полное per-cabinet покрытие подтверждённого exact join Finance/goods-return;
  положительный goods-return gate доказывает совместимый crosswalk, но не
  обещает полное покрытие каждой строки.
- Claims identity: в текущем окне source keys отсутствуют, поэтому применимый
  exact crosswalk и возможность R-2 ещё не доказаны.
- Фактическая history depth goods-return за пределами одного 31-дневного
  request window; официальный контракт её не гарантирует.
- Нормализованный справочник категорий `reason` (версионировать ли, как
  классификатор логистики).

# Changelog

- 2026-07-22 — после отдельно разрешённого production full source refresh из
  `e0d6578` создан новый неопубликованный immutable draft: verified
  file-authoritative Finance без DB rows/ambiguity, logistics context `ready`,
  current report и flags не изменены. Повторный boolean-only R-0I подтвердил
  exact `goods-return.srid → Finance.srid` и canonical return chain;
  `goodsReturnIdentityGate=true`. Claims keys отсутствуют, поэтому
  `claimsIdentityGate=false`, `completeIdentityGate=false`,
  `contractChangeRequired=true` и `implementationGate=false` до отдельного
  accepted-решения.

- 2026-07-22 — выполнен read-only R-0L: среди существующих immutable reports
  не найден verified unambiguous Finance return lineage. Report candidates и
  return fact присутствуют, но production selector повторно зафиксировал
  source integrity failure и DB/file ambiguity. `newReportRequired=true`,
  автоматическое reuse отсутствует, implementation gate закрыт. Создание нового
  report, migration/runtime rollout и retention mutation этим evidence не
  разрешены.

- 2026-07-22 — перед любым новым full/report принят read-only R-0L existing
  lineage discovery. Он newest-first проверяет прежние immutable reports тем же
  production selector, но публикует только booleans и ничего не выбирает/не
  создаёт. Это отделяет необходимость нового report от возможности безопасно
  повторить R-0I на уже существующем verified unambiguous lineage.

- 2026-07-22 — R-0I live probe прошёл внешний source gate, но fail closed на
  DB/file ambiguity выбранного Finance snapshot. Verified lineage и exact
  candidate evaluation не подтверждены; goods-return/claims/complete identity
  gates остаются закрыты. Диагностика сделана совместимой с pre-factor schema,
  изолирует scope transactions и публикует только безопасные failure booleans.
  Следующий шаг — новый immutable report из однозначного verified storage;
  R-1…R-5, production/client enable и изменение существующего join запрещены.

- 2026-07-22 — после закрытого R-0 direct join принят отдельный R-0I contract:
  сравнивать только same-name `srid↔srid` и `orderId↔orderId` на verified
  Finance lineage, разрешать candidate в единственный canonical return chain и
  публиковать только boolean evidence. Cross-field/product/date fallback и
  автоматическое изменение implementation join запрещены.

- 2026-07-22 — boolean-only R-0 live gate подтвердил source schema и валидные
  scoped keys, но не подтвердил ни одного exact Finance/source match на
  выровненном максимальном window. `implementationGate=false`; R-1…R-5
  остановлены до отдельного identity evidence без ослабления join.

- 2026-07-22 — статус изменён на `accepted` после подтверждения пользователем и
  повторной сверки официального WB OpenAPI: `claims.is_archive` закреплён как
  boolean, active/archive ограничены текущими 14 днями, добавлены pagination и
  provider-total gate; goods-return сохраняет максимум 31 день на запрос без
  обещанной history depth. Приняты exact cabinet/srid/nm join, boolean-only R-0,
  PII-free flat/mart/API, отдельный context, flags, state/role matrix,
  atomicity/readiness и staff-only rollout. Существующий goods-return client
  отмечен как prework, не end-to-end реализация.

- 2026-07-19 — создан draft источника причин возвратов по запросу продолжить
  план разработки: зафиксированы отдельные read-only источники `goods-return`
  (reason, окно 31 день, 1 запрос/мин) и `claims` (user_comment, окно 14 дней +
  архив, обязательный `is_archive`, 20 запросов/мин) с перепроверкой официальных
  WB API, план probe покрытия, связывание по `srid` с явными `unmatched`,
  витрина `report_logistics_return_reason_rows`, модель факт/гипотеза/недоступно,
  безопасная обработка персональных данных покупателя, крайние случаи,
  acceptance, rollout/rollback и открытые вопросы. Живой probe не выполнялся;
  контракты полей помечены как требующие построчной сверки по Swagger.
  Источник намеренно не смешивается с готовым Finance gate первой очереди.
