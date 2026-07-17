---
spec_id: "wb-unit-economics-source-refresh-hardening-provider-registry"
title: "Shumeyko source refresh hardening and provider registry"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
truth_scope: source-refresh
truth_priority: 100
related_code:
  - src/wb_unit_economics/calculation.py
  - src/wb_unit_economics/contracts.py
  - src/wb_unit_economics/web/app.py
  - src/wb_unit_economics/web/database.py
  - src/wb_unit_economics/web/repository.py
  - src/wb_unit_economics/web/source_refresh.py
  - src/wb_unit_economics/web/providers.py
  - src/wb_unit_economics/web/static/app.js
  - scripts/rebuild_report_from_sources.py
  - scripts/prune_source_refresh.py
related_tests:
  - tests/test_calculation.py
  - tests/test_marketplace_daily_facts.py
  - tests/test_web_database.py
  - tests/test_web_app.py
  - tests/test_source_refresh.py
  - tests/test_provider_registry.py
  - tests/test_source_refresh_prune.py
contracts: [wb_api_snapshot, onec_unf_cost_snapshot, sku_mapping, unit_economics_report]
depends_on:
  - docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md
  - docs/specs/wb-unit-economics-db-first-report-marts.md
  - docs/specs/marketplace-1c-mapping-service.md
supersedes: []
rollout_required: true
updated_at: "2026-07-17"
---

# Implementation Status

Статус остается `accepted`. Worker, provider registry, guards и retention CLI
реализованы, однако безопасный документационный прогон не запускает полный
production refresh, watchdog и recovery. Для `implemented` требуется отдельная
матрица acceptance criteria с локальными тестами и live evidence.

# Goal

Стабилизировать регулярный `source_refresh` перед расширением read-only
интеграций и убрать hard-code WB/1C из API/UI слоя подключений.

# Scope

Входит:

- preflight guard по свободному месту до внешних WB/1C чтений;
- блокировка конфликтующих запусков `source_refresh`;
- dry-run prune CLI для старых raw snapshot directories;
- provider registry для read-only интеграций;
- metadata в `GET /api/integrations`;
- collector contract для текущих источников refresh.
- staff-only UI/API в разделе интеграций для загрузки mapping, dry-run проверки
  и ручного `full` refresh по выбранному клиентскому контуру.
- live metadata guard 1С перед тяжелыми чтениями WB/Ozon;
- отдельный runtime-status интеграции, не смешанный с последней ручной
  проверкой;
- degraded health при свежем неуспешном source refresh;
- ограниченная автоматическая очистка старых директорий завершенных failed
  runs.
- адаптивная постраничная загрузка тяжелых 1С OData коллекций с immutable
  checkpoint и продолжением в новом `source_refresh_run`.

Не входит:

- подключение новых маркетплейсов;
- запись во внешние системы;
- изменение расчетной методики;
- автоматическое удаление snapshots успешных runs или snapshots, связанных с
  опубликованными отчетами.

# Runtime Guards

`source_refresh` обязан завершаться без внешних API-вызовов:

- `blocked_low_disk`, если на файловой системе `source_refresh_root` меньше
  `SHUMEYKO_SOURCE_REFRESH_MIN_FREE_GB`, default `8`;
- `blocked_active_refresh`, если `daily` стартует во время активного `full`, или
  если стартует второй активный run того же режима.

Blocked run сохраняется в `source_refresh_runs`, получает `finished_at` и
понятное safe-сообщение. Это нужно, чтобы systemd/health видели причину, а не
молчаливый пропуск.
CLI `run_source_refresh.py` завершает управляемые blocked statuses кодом `0`,
чтобы oneshot-unit не переходил в failed из-за штатного guard; health helper
остается источником alert-сигнала и возвращает `1` для blocked statuses.
Для неожиданных исключений `error_message` хранит тип ошибки и короткое
очищенное сообщение без длинных token/password/secret-подобных значений, чтобы
следующий incident был диагностируемым без чтения raw payloads или `.env`.
Новый report run сохраняется как draft и публикуется current только последним
шагом после source loads, финального статуса refresh и audit-записи; если после
сборки отчета случается ошибка, предыдущий published report остается текущим.

До внешних collectors для WB/Ozon `source_refresh` выполняет read-only
`GET .../$metadata` для обязательной 1С OData интеграции. Успешным считается
только `HTTP 200` с валидным EDMX XML и `EntityContainer`. При `404`, сетевой
ошибке или HTML вместо metadata run завершается `failed` до тяжелых загрузок
WB/Ozon. Результат сохраняется как обязательная коллекция
`onec_odata_metadata` и как безопасный `lastRuntimeCheck` интеграции без URL,
логина, пароля и response body.

Ручной `lastCheck` и автоматический `lastRuntimeCheck` — разные сигналы. UI
показывает более новый из них: успешная ручная проверка не должна скрывать
более поздний сбой scheduler, а последующее успешное runtime-чтение снимает
деградацию.

`GET /api/health` возвращает `status=degraded`, если последний завершенный
refresh имеет статус `failed`, `needs_configuration`, `blocked_low_disk` или
`blocked_active_refresh`. Активный новый run не скрывает предыдущий завершенный
сбой до своего успешного завершения.

# Provider Registry

Внутренний registry хранит для каждого базового провайдера:

- `providerBase`;
- label;
- read-only roles и default role;
- read-only check handler;
- `supportsMultiple`;
- `primaryProviderId`.

Первый registry содержит `wb_api` и `onec_readonly`. Существующие provider IDs и
payload `tenant_integrations` сохраняются совместимыми.

`GET /api/integrations` возвращает прежний `items` и новый `providers`.
Секреты, raw payloads и connection strings не возвращаются.

# Source Collectors

Текущий refresh использует `SourceCollector` contract:

- `sku_mapping`;
- `wb_product_cards`;
- `wb_finance_detail`;
- `wb_sales_report_list`;
- `wb_redeem_notifications`;
- `onec_odata`.

После реализации `docs/specs/marketplace-1c-mapping-service.md` `sku_mapping`
берется из собственного сервиса сопоставления. Source refresh регулярно грузит
WB cards через read-only collector `wb_product_cards`, пересчитывает кандидатов
из read-only WB/Ozon/1С snapshots и проверяет свежесть current mapping view.
TXT/TSV/CSV upload остается только emergency fallback и импортом кандидатов без
записи в 1С, WB или Ozon.

План режимов:

- `daily`: mapping, WB product cards, WB finance, 1C OData;
- `incremental`: mapping, WB product cards, WB finance за последние `28`
  календарных дней, WB report list, optional WB primary redeem notifications,
  свежая provider-window история остатков и 1C OData; режим атомарно заменяет
  окно `marketplace_finance_daily_facts` и создает полный immutable staff draft
  из накопленной дневной витрины без перечитывания полной raw-истории;
- `weekly` и `full`: mapping, WB product cards, WB finance, WB report list,
  optional WB primary redeem notifications, 1C OData;
- `onec-only`: mapping, 1C OData.

`daily` остается source-only обновлением и не создает отчет. `incremental`
доступен только при `SHUMEYKO_SOURCE_REFRESH_INCREMENTAL_ENABLED=true` и
`SHUMEYKO_MARKETPLACE_DAILY_FACTS_ENABLED=true`, а сборка выполняется только при
`SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true`. Отчетный период incremental начинается
с даты начала текущего опубликованного отчета и заканчивается вчерашним днем;
отдельные `source_window_start/source_window_end` фиксируют фактически повторно
прочитанные последние `28` дней. Ozon в incremental не входит и продолжает
обновляться отдельным `ozon-only` действием.

Перед внешним чтением incremental обязан найти совместимый завершенный `full`,
проверить materialized/persisted parity дневной витрины и непрерывность
заявленных coverage-интервалов. После загрузки окно заменяется целиком, включая
удаление исчезнувших строк. Затем полный P&L строится из
`marketplace_finance_daily_facts`, а себестоимость всех строк заново подбирается
по свежему снимку 1C. Небольшие WB document sources объединяются по правилу
`base до границы + current overlay`; stock history используется только из
свежего provider window без экстраполяции. Если базы нет, coverage разорван или
parity не подтвержден, run завершается `needs_full_refresh`; скрытый fallback на
`full` запрещен.

Составной lineage хранит `coverage_start/coverage_end` и `lineage_role` со
значениями `base`, `overlay` или `current` в `SourceLoad`. Composite
`source_snapshot_set_id` является детерминированным hash версии методики,
базового full и всех contributing WB overlay, mapping и 1C snapshots. Retention
защищает каждый run, на который ссылается хотя бы один `SourceLoad`.

`onec-only` без `source_report_run_id` остается source-only загрузкой. Если
указан исходный отчет, режим обязан создать новый immutable staff draft: новый
1С/mapping/tax snapshot объединяется с последним полным WB snapshot того же
клиента, который покрывает весь период отчета, имеет загруженные обязательные
WB-коллекции и физически существует. Зависимость фиксируется полем
`base_source_refresh_run_id`; `SourceLoad` нового draft сохраняет исходный run
для каждой коллекции, а `source_snapshot_set_id` является детерминированным
composite hash. Если подходящего WB snapshot нет, web auto-refresh выбирает
`full` вместо `onec-only`. Ни один из режимов не публикует draft автоматически.

Новые провайдеры можно сохранять и проверять read-only через registry, но они не
попадают в расчет без отдельного accepted spec для collector, lineage и формул.

## 1C OData pagination and resume

`Document_ОтчетКомиссионера` и `Document_РасходнаяНакладная` читаются
страницами по `5` заголовков с явным `$select`: идентификатор, дата, номер,
статус проведения, входящий номер/комментарий и документные суммы. Тяжелые
товарные табличные части в эти snapshots не входят; режим `header_only`
фиксируется в collection manifest и source-refresh collection lineage. Для
детальной Ozon-сверки отсутствие этих строк означает `needs_review`, а не ноль.
`Document_ПриходнаяНакладная` сохраняет необходимые финансовые табличные части
`Расходы` и `Запасы` и помечается как `financial_tables`. Вложенные регистры
используют меньшие collection-specific страницы, описанные ниже. При
`ReadTimeout` размер текущей страницы уменьшается до безопасного минимума;
каждый размер допускает исходный запрос и до трех повторов с паузами `2/5/15`
секунд. Live 1С возвращает `HTTP 500` на серверный фильтр по `Edm.DateTime`,
поэтому документы читаются только со стабильным `Posted eq true`, малыми
страницами и сортировкой `Date,Ref_Key`; ограничение отчетного периода по
`Date` выполняется при нормализации и фиксируется как
`local_document_date` в manifest.
В опубликованной 1С OData-модели регистры `Запасы`, `ЗапасыНаСкладах`,
`Продажи`, `ДоходыИРасходы` и взаиморасчеты возвращают верхнеуровневые записи
`Recorder/RecordSet`; поле `Period` находится внутри вложенного `RecordSet`.
Поэтому серверный `$filter=Period...` для них недопустим. Такие источники
читаются небольшими батчами со стабильной сортировкой по `Recorder`, а период
ограничивается при нормализации вложенных строк; режим
`nested_recordset_local` явно фиксируется в manifest. Размеры страниц
подбираются по фактическому весу recorder: `Продажи=2`, `Запасы` и
`ЗапасыНаСкладах=25`, `ДоходыИРасходы=50`, взаиморасчеты=`100`.

Каждая успешно прочитанная страница немедленно сохраняется отдельным raw JSON,
после чего атомарно обновляется collection manifest с хешем query contract,
хешами страниц, числом строк, фактическим page size и следующим OData cursor.
При сбое после одной или нескольких страниц коллекция получает
`partial_source` и сохраняет фактические `row_count/page_count`; недоступные
данные не заменяются нулем. После полного чтения рядом потоково собирается
обратносуместимый `<sample_id>.raw.json` для существующих loaders.
1С snapshot больше `25 MiB` не дублируется строками в PostgreSQL: raw files и
их hashes остаются authoritative, а collection payload получает
`rowPersistence.status=skipped_large_snapshot`. Перед долгим внешним чтением
текущая DB-транзакция завершается, чтобы idle PostgreSQL connection не
удерживался на время OData download.

Resume не изменяет каталог завершенного запуска. Новый run получает новый
`snapshot_set_id`, `resumed_from_run_id` и может использовать только
совместимый checkpoint того же клиента, 1С-контура, периода, коллекции и query
contract. Каждая переиспользуемая страница сначала проверяется по хешу и затем
копируется или hard-link-ится в новый snapshot. Поврежденный или несовместимый
checkpoint игнорируется, коллекция читается заново. Завершенные compatible
collection checkpoints переиспользуются без повторного запроса в 1С; у
аварийно завершенного run принимается последний атомарный `running` manifest,
а `max_pages` считается бюджетом новых страниц, поэтому следующий run реально
продвигает cursor. По умолчанию web/API и CLI
используют `resumeMode=auto`; `never` принудительно начинает чистый snapshot,
а staff может явно передать `resumeFromRunId`.

`commissioner_reports` является publication-required: его сбой допускает
staff draft, но блокирует публикацию и закрытие документной сверки.
`stock_movements` остается optional и дает предупреждение, если обязательный
`sales_register` и сверка себестоимости подтверждены. Поле `required`
сохраняет прежнюю совместимость, новое `publication_required` явно отделяет
барьер построения от барьера публикации.

## Lineage-aware retention

Retention защищает source-refresh каталоги, на которые ссылаются `SourceLoad`
draft/published отчетов, активные runs и рекурсивные
`base_source_refresh_run_id`. Ссылка считается по фактическому `root_dir` и
`snapshot_set_id`, поэтому legacy report с пустым `source_snapshot_set_id`, но
валидным `SourceLoad.source_refresh_run_id`, также защищен. Если PostgreSQL
недоступен, `prune_source_refresh.py --apply` завершается до удаления; dry-run
показывает ошибку. Storage audit возвращает ошибку `missing_report_lineage`,
если защищенный DB run указывает на отсутствующий каталог.

## WB finance pagination and resume

WB finance также сохраняется постранично. После каждой успешно прочитанной
страницы атомарно обновляется `wb_finance/manifest.json` с границами периода,
последним `rrd_id`, числом и хешами страниц. При аварийной остановке manifest
может быть восстановлен только из уже сохраненных immutable page-файлов; их
целостность повторно проверяется по хешам.

Следующий совместимый `source_refresh_run` получает новый `snapshot_set_id`,
копирует или hard-link-ит подтвержденные WB-страницы в новый snapshot и
продолжает чтение с последнего `rrd_id`. Полностью завершенный WB checkpoint
переиспользуется без повторного внешнего запроса. Отсутствующий, поврежденный
или несовместимый manifest не считается нулевым источником: WB читается заново,
а частичный результат остается `partial_source` и блокирует публикацию.

# Staff Refresh Control UX

Для нового клиента нельзя зависеть от уже опубликованного отчета: у такого
клиента может еще не быть `report_run`, поэтому импорт кандидатов и первый
`full` refresh доступны в staff-only блоке `Данные и расчёт` на главной странице.
Сам интерактивный сервис сопоставления открывается отдельным виджетом из основной
очереди `Что разобрать первым`, когда в контуре уже есть позиции, требующие
решения. `Интеграции` используются только для настройки подключений.

Требования:

- `consultant/admin` видит на главной странице перед KPI отдельный блок
  `Данные и расчёт`, который загружается независимо от окна интеграций;
- блок показывает последний `source_refresh` выбранного клиента: статус, режим,
  период, safe-сообщение, новый report id и статусы коллекций без raw payloads,
  секретов и connection strings;
- production web только создает immutable run со статусом `queued` и запускает
  отдельный systemd worker `shumeiko-source-refresh-worker@<run_id>`; рестарт
  web не прерывает WB/1С чтение, а worker выполняет существующий run вне cgroup
  web с `MemoryHigh=2G`, `MemoryMax=3G` и `MemorySwapMax=1G`; при давлении
  памяти systemd-oomd завершает этот фоновый worker раньше SSH, PostgreSQL и
  системных служб, а `ExecStopPost` сохраняет управляемый статус ошибки;
- это правило распространяется на основной source-refresh API, совместимую
  кнопку дозагрузки 1С, AI-команду, автоматическую пересборку после загрузки
  сопоставления и production daily/weekly CLI. Синхронный
  `SourceRefreshService.run(dry_run=false)` внутри web запрещен;
- run хранит `worker_id`, `heartbeat_at`, `failure_code` и `blocked_by_run_id`.
  Heartbeat обновляется не реже чем раз в 30 секунд; watchdog раз в минуту
  завершает worker без heartbeat за 5 минут и только после остановки процесса
  переводит run в `failed`, не удаляя snapshots и collections;
- API сохраняет совместимое поле `latest` и отдельно возвращает `activeRun`,
  `latestAttempt` и `latestCompleted`. Заблокированная попытка остается в
  истории, но не подменяет прогресс реально активного run;
- safe API дополняет run агрегированным `progress`: этап, текущий источник,
  число WB-страниц/строк, записанный объем и завершенные кабинеты. Данные
  читаются из атомарного manifest без публикации account ids и raw payloads;
- если более поздняя автоматическая попытка получила `blocked_active_refresh`,
  блок продолжает показывать реально активный refresh, а после его завершения —
  результат содержательного запуска, а не технически заблокированную попытку;
- staff открывает сервис сопоставления из карточки `Сопоставление WB ↔ 1C` в
  `Что разобрать первым`, пересчитывает кандидатов и принимает ручные решения в
  отдельном виджете; импорт TXT/TSV/CSV mapping WB ↔ 1C на уровне клиента
  остается fallback-действием блока обновления данных, сохраняется в
  `SHUMEYKO_SOURCE_REFRESH_MAPPING_DIR`, а audit пишет только имя и размер файла;
- staff может запустить dry-run через `/api/clients/{client_id}/source-refresh`
  с `dry_run=true`, чтобы проверить конфигурацию без внешних WB/1C чтений;
- staff может запустить явный `full` refresh через тот же endpoint с
  `mode=full`; запуск использует encrypted tenant integrations и создает новый
  report run только если mandatory sources прошли;
- клиентская роль не видит эти controls и получает `403` на staff endpoints;
- если refresh уже идет, source refresh guard возвращает safe статус
  `blocked_active_refresh`, а UI показывает это как штатную занятость.

# Retention

`scripts/prune_source_refresh.py` по умолчанию работает как dry-run. При
`--apply` удаляются только старые direct child directories внутри
`data/source_refresh` или заданного `--source-root`.

Защищены:

- последние `daily-*` директории, default `3`;
- последние `full-*` директории, default `2`;
- snapshot ids draft/published report runs и их `SourceLoad` lineage из БД;
- незавершенные refresh runs, рекурсивные composite bases и последний успешный
  полный WB snapshot каждого клиента.

Скрипт не трогает `.env`, `reports`, `data/web`, PostgreSQL и любые пути вне
`source_refresh_root`.

После завершения run со статусом `failed` сервис автоматически удаляет только
старые direct-child директории других завершенных failed runs того же tenant.
Текущий failed snapshot и последние
`SHUMEYKO_SOURCE_REFRESH_FAILED_SNAPSHOT_KEEP` failed snapshots сохраняются;
default `2`. Директории active runs, successful runs, published report
snapshots, symlinks и пути вне `source_refresh_root` не удаляются. Ошибка
cleanup не меняет статус refresh и не должна скрывать исходную ошибку.

## File-authoritative marketplace facts

WB Finance и Ozon всегда сначала сохраняют immutable raw-файлы и manifest.
Настройка `SOURCE_REFRESH_RAW_DB_MODE` принимает `legacy` или `files_only`.
Режим `legacy` временно сохраняет прежние `source_snapshot_rows` для теневого
сравнения. В `files_only` marketplace raw rows не создаются, а collection
получает `rowPersistence.status=file_authoritative`.

При включенном `SHUMEYKO_MARKETPLACE_DAILY_FACTS_ENABLED` расчет после нормализации и
строкочувствительных распределений атомарно заменяет текущее окно таблицы
`marketplace_finance_daily_facts`. Ее grain:

`tenant/client/marketplace/cabinet/organization/day/report/document/product/`
`sales_model/operation_group`.

Витрина хранит только типизированные измерения, аддитивные финансовые меры,
`source_row_count`, общий digest row hashes, partial-source status,
`source_snapshot_set_id` и methodology version. Она не заменяет immutable raw
snapshot для воспроизводимости и не меняет публичный web API.

Дневной факт хранит уже рассчитанные COGS, gross profit, контролируемые расходы,
входной НДС WB/1С, выбранный для P&L сервисный входной НДС и распределенную
скидку СПП. При DB-first rebuild эти значения считаются предрассчитанными:
расчет не применяет к ним повторное распределение, не выбирает повторно между
WB- и 1С-источником НДС и не пересчитывает COGS или gross profit из округленной
дневной quantity. Копеечный residual COGS и gross profit детерминированно
согласуется внутри конечного weekly report grain. Report-list по-прежнему
задает тип документа, дату ведомости и контрольные totals, но не меняет
сохраненное распределение между строками. Для существующей БД поля
`spp_discount`, `accounting_service_input_vat` и `gross_profit` добавляются
аддитивной идемпотентной миграцией; после миграции нужен новый `full`, потому
что прежние дневные факты не содержат эти исторические аллокации.

Замена выполняется через staging/load-id и всегда охватывает полный заявленный
интервал `period_start..period_end`, включая пустой хвост. До promotion staging
проверяются grain/count/digest; delete+promotion выполняются одной транзакцией.
Отдельная persisted parity повторно читает рабочую таблицу и сравнивает ее с
отфильтрованными generated facts.

Incremental материализует заменяемое окно из текущего raw WB и текущего
report-list overlay. Технический период materialization расширяется до
полных границ недель, содержащих
`date_from..max(date_to, create_date)` относящихся к окну ведомостей. В рабочую
витрину входят строки календарного интервала
`source_window_start..source_window_end`, а также строки тех же стабильных
`seller_account_id + marketplace_report_id`, даже если дата операции вышла за
календарную границу ведомости. Замена выполняется по интервалу и по этим
report keys. При сборке
отчета facts выбираются по полному composite report-list `base + current
overlay`. Стабильная пара кабинета и report ID ограничивает атомарную замену,
но расчетная неделя по-прежнему определяется по `fact_date`. DB selection
использует те же недельные границы, что и calculation: от начала недели
`period_start` до конца недели `period_end`. Это сохраняет неполные граничные
weekly documents без повторного расчета всей raw-истории и без перераспределения
facts между неделями.

Staging digest считается потоково в том же canonical JSON формате, что и
целостный список, без создания дополнительных полных копий многомиллионной
витрины в памяти. Удаление временной загрузки выполняется ограниченными batch,
чтобы не упираться в statement timeout после успешного promotion.

Calculation parity разделена на два независимых контроля: legacy DB rows против
file-stream report и generated daily facts против persisted daily facts. Первый
сравнивает по stable business grain все строки отчета, KPI, document
reconciliation, налоги, статусы качества, source counts и hashes. Aggregate-only
сверка не может выставить `calculationParity.status=matched`; полный результат
сохраняется отдельным JSON-артефактом и в additive collection payload.

Aggregate parity дневной витрины требует точного совпадения количества и всех
денежных показателей, включая себестоимость. Перед сохранением дневных фактов
копеечный residual себестоимости детерминированно распределяется внутри того же
report grain, поэтому сумма дневной витрины должна совпадать с отчетом без
допуска. Контрольная сумма каждого grain берется из той же уже округленной до
копеек недельной строки отчета, а не вычисляется повторным сложением дневных
неокругленных подгрупп: порядок сложения длинных `Decimal` не может изменить
результат на границе половины копейки. Поле `roundingTolerance.cogs` сохраняется
для совместимости со значением `0.00`; любая ненулевая дельта блокирует
promotion.

При composite rebuild, который обновляет только 1С, общий raw-integrity verifier
проверяет WB finance и WB report-list в базовом refresh run. Отсутствие collection
в техническом child run не считается отсутствием raw-источника, но повреждение
файлов базового run по-прежнему блокирует rebuild.

При resume immutable snapshot каталог первичных документов WB переносится целиком,
включая вложенные подписанные архивы и account manifests, через hard link с
безопасным fallback на копирование. Повторный run использует сохраненные provider
results и не обращается к Documents API повторно.

Ozon параллельно материализует текущие типизированные
`marketplace_operation_facts` с уникальным source/business key. До перевода
всех Ozon diagnostics на эти facts production остается в `legacy`; переключение
на `files_only` выполняется только после parity-check на одном snapshot и
отдельного включения `SOURCE_REFRESH_OZON_FILES_ONLY_ENABLED`. Общий
`SOURCE_REFRESH_RAW_DB_MODE=files_only` без этого флага переключает WB, но не
прекращает совместимую raw-запись Ozon.

Typed Ozon grain не зависит от позиции строки и включает cabinet/source type,
operation, posting, product и service key. Service lines и partial-source status
хранятся типизированно; promotion выполняется атомарно через staging. Raw Ozon
можно отключить только после typed parity для всех источников, используемых P&L
и diagnostics.

Поддерживаемый file-authoritative контур включает
`ozon_finance_cash_flow`, `ozon_realization`, `ozon_realization_posting`,
`ozon_mutual_settlement`, `ozon_products_buyout`, `ozon_b2b_sales_json` и
`ozon_products_report`. Асинхронные ответы создания/опроса отчета проверяются
по hash как raw-файлы, но не входят в collection data row count и typed facts.

`typedParity.status=matched` требует одновременно verified raw integrity,
полного source-row coverage, совпадения file normalization с legacy DB rows,
совпадения staged/persisted typed facts и полной legacy/typed сверки публичной
Ozon diagnostics/P&L. Последняя выполняется по всем строкам snapshot, денежные
поля сравниваются после рабочего округления, а preview-строки сортируются по
stable business grain; физический SQL-порядок и технические row ids не являются
grain. Артефакт сохраняет только digests, статусы секций и пути расхождений.

Cash-flow сохраняется typed summary и service lines по категориям и операциям;
mutual-settlement сохраняет документные строки, а buyout/B2B разворачивают
вложенные `products`, `invoices` и `operations`. Повторная материализация того
же snapshot атомарно заменяет текущие facts и не увеличивает их число.

# Acceptance Criteria

- Low-disk guard не вызывает WB/1C exporters.
- Недоступная или невалидная 1С `$metadata` не вызывает WB/Ozon exporters.
- Runtime-status 1С показывает более новый автоматический сбой отдельно от
  последней ручной проверки.
- `/api/health` показывает `degraded` при свежем завершенном failed refresh,
  в том числе пока следующий run еще active.
- Active full блокирует daily статусом `blocked_active_refresh`.
- Все `daily/incremental/weekly/full` одного клиента сериализованы: scheduler не
  может заменить daily-facts окно во время incremental rebuild.
- Provider registry отдает WB/1C metadata и default roles.
- `/api/integrations` совместим по `items` и содержит `providers`.
- staff-only mapping service сохраняет решения и импорт кандидатов без
  публикации raw содержимого в API/audit.
- Source refresh проверяет mapping service, а отсутствие старой папки
  `data/onec_marketplace_mapping` не считается самостоятельным blocker.
- `/api/clients/{client_id}/source-refresh` staff-only запускает dry-run или
  `full`/`incremental` refresh и возвращает safe payload последнего run;
- два последовательных incremental run повторяемы, не создают дублей и на
  текущем production объеме завершаются не более чем за `10` минут;
- incremental и full на одинаковых frozen sources совпадают до копейки по KPI,
  строкам, налогам, себестоимости, расходам, сверкам, lost sales и Excel;
- отсутствие compatible full, разрыв coverage или неподтвержденный parity дает
  `needs_full_refresh` и отдельное действие полной пересборки, не скрытый full;
- production `full` из web продолжает выполняться после рестарта web-сервиса;
  повторный worker не может одновременно забрать уже выполняющийся run.
- full-refresh не выполняется через FastAPI `BackgroundTasks`; health и статика
  отвечают во время пересборки, а PostgreSQL-транзакция завершается перед
  файловой сборкой и экспортом артефактов.
- stale worker получает `failed` с сохранением коллекций; повтор запускается
  новым immutable run с `resume_mode=auto`.
- production daily/weekly после создания run запускают тот же systemd worker;
  fallback `cli:<pid>:<run_id>` разрешен только для SQLite/dev. Watchdog может
  завершить legacy CLI run лишь после подтверждения, что указанный PID больше
  не существует;
- активный WB manifest отражается в safe `progress` без account ids, имен
  кабинетов, путей и raw payloads.
- UI главной страницы перед KPI содержит `Данные и расчёт` с fallback upload
  mapping, dry-run, full refresh и статусом коллекций; раздел `Интеграции`
  содержит только настройки подключений, а интерактивный mapping service вынесен
  в отдельный виджет основной очереди `Что разобрать первым`.
- `prune_source_refresh.py` dry-run ничего не удаляет.
- Автоочистка failed snapshots сохраняет минимум два последних failed runs и
  не выходит за direct children `source_refresh_root`.
- Non-SQLite SQLAlchemy engine использует `pool_pre_ping` и `pool_recycle`.
- Тесты, ruff, docs validators и no-secrets validators проходят.
- Таймаут тяжелой 1С страницы уменьшает batch без потери уже сохраненных
  страниц; следующий совместимый run продолжает с checkpoint без дублей.
- Аварийная остановка WB после любой страницы сохраняет manifest; следующий
  совместимый run продолжает с последнего `rrd_id` без повторной загрузки уже
  подтвержденных страниц.
- `commissioner_reports=partial_source/failed` блокирует публикацию, а
  optional `stock_movements` не превращается в ноль и не блокирует отчет при
  подтвержденной обязательной себестоимости.

# Rollout

1. Применить код и документацию.
2. Запустить локальные проверки.
3. Проверить live `/api/health`, `/api/integrations` 401 без авторизации,
   `/.env` 404.
4. Проверить `scripts/check_source_refresh_health.py --systemd`.
5. Включать или перезапускать daily timer только после проверки, что active full
   завершен и disk guard больше не блокирует нормальный refresh.

# Changelog

- 2026-07-17: tied daily-fact COGS residual reconciliation to the exact rounded
  controls of final weekly report rows, eliminating order-sensitive Decimal
  re-aggregation while retaining zero tolerance.
- 2026-07-13: persisted the allocated SPP discount and marked daily-fact COGS,
  controlled expenses and input VAT as precomputed during DB-first rebuild, so
  incremental output does not repeat cent-sensitive allocations.
- 2026-07-13: fixed incremental daily-facts replacement and report selection to
  preserve operations outside a calendar boundary when their stable report ID
  belongs to the replaced WB statement window.
- 2026-07-13: accepted the feature-flagged 28-day `incremental` WB + 1C mode,
  daily-facts report input, composite coverage lineage, serialized client
  refreshes and explicit `needs_full_refresh` fallback contract.
- 2026-07-12: lowered the independent worker memory ceiling to 3 GiB, limited
  worker swap to 1 GiB and enabled systemd-oomd preference so a heavy refresh
  fails safely instead of exhausting the whole server and breaking SSH.
- 2026-07-12: added exact cent-level WB COGS reconciliation, streaming staging
  digest, batched staging cleanup and base-run raw verification for composite
  rebuilds.
- 2026-07-11: unified web, compatible 1C, AI, mapping-upload and scheduled
  refresh submission through queued systemd workers; added conservative stale
  legacy CLI recovery without deleting immutable data.
- 2026-07-11: moved production web refresh execution to an independent systemd
  worker, added worker heartbeat/watchdog, separated active run from latest
  attempt and protected immutable checkpoints during recovery.
- 2026-07-11: made the staff refresh status prefer the real active run and skip
  later `blocked_active_refresh` timer attempts when selecting the visible result.
- 2026-07-11: moved source-refresh status and controls from `Интеграции` to the
  main `Данные и расчёт` panel and decoupled its loading from integration cards.
- 2026-07-11: moved the interactive mapping queue out of `Интеграции` into a
  separate widget opened from `Что разобрать первым`; integrations retain the
  client-level fallback upload and source-refresh controls.
- 2026-07-11: added atomic WB finance page checkpoints, manifest recovery and
  immutable cross-run resume without duplicate downloads.
- 2026-07-10: added adaptive 1C OData batches, immutable per-page checkpoints,
  cross-run resume lineage and publication-required source semantics.
- 2026-07-10: added fail-fast 1C EDMX metadata guard, runtime integration
  status, degraded health and bounded failed-snapshot cleanup.
- 2026-07-08: switched mapping freshness/readiness to the project-owned
  marketplace/1C mapping service; file upload remains fallback candidate import.
- 2026-07-04: added staff refresh control UX/API for client-level mapping
  upload, dry-run readiness check and manual full refresh from integrations.
- 2026-06-24: accepted spec for source refresh hardening, provider registry,
  collector contract and retention CLI.
