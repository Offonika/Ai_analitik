---
title: "Operational state WB-логистики"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "agent", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-logistics-cost-analysis-implementation.md"
updated_at: "2026-07-22"
---

# Назначение

Этот handoff нужен для продолжения работы в новом чате. Он не заменяет
accepted-спецификацию. При расхождении следовать `AGENTS.md`,
`docs/manifest.yml` и
`docs/specs/wb-logistics-cost-analysis-implementation.md`.

Последнее записанное operational evidence датировано **21 июля 2026 года**.
Перед любым утверждением о текущих feature flags, runtime, gate или rollout
обязательно повторно проверить соответствующую среду; приведенное ниже
состояние не является доказательством на более позднюю дату. Code defaults
не подтверждают фактическое состояние test или production.

На test развернут чистый immutable release
`runtime-main-fe0f229-logistics-f4-v2-20260721`. Master-флаги факторов и F-4
включены только для staff; factor- и measurement-client flags, а также client
login выключены. Новый F-4 draft из verified read-only snapshots сохранен, но
не опубликован. Production остается на
`runtime-fcfc52b-tax-profile-configured-20260721`; production и клиентское
включение F-4 не выполнялись.

# Текст для нового чата

```text
Продолжи работу в /opt/shumeyko-partners-wb-unit-economics по WB-логистике v5.
Сначала запусти compact route для scope `logistics-cost-analysis` и проверь
операционное состояние в этом runbook. На test развернут immutable release
runtime-main-fe0f229-logistics-f4-v2-20260721 из main merge fe0f229. Factor и
F-4 master включены для staff, оба client-флага и client login выключены.
Неопубликованный immutable draft имеет partial measurement context без
blocking reasons; справочные суммы F-4 исключены из финансовых KPI до сверки.
Staff API/UI, desktop 1440x900 и mobile 390x844 приняты; client-role получает
HTTP 404, блок скрыт и запрос не выполняется. Временные пользователи, пароли,
сессии, browser script и screenshots удалены. Production не менять без
отдельного разрешения; production runtime и client flags не менялись.
```

# Текущее состояние

- Базовая методика логистики — `wb-logistics-v5`, методика F-4 —
  `wb-logistics-measurements-v1`; поддерживается только WB.
- F-4 реализован в `main` через PR №49; визуальное исправление desktop-таблицы
  влито через PR №50. Test runtime собран из точного merge-коммита PR №50 с
  `sourceDirty=false`.
- Test health подтверждает `runtimeEnvironment=test`, совпадающие backend/static
  build `20260721-logistics-f4-measurements-v2`, schema
  `2026_07_21_logistics_measurements_context_v1` и `status=ok`.
- На test включены `SHUMEYKO_LOGISTICS_FACTORS_ENABLED=true` и
  `SHUMEYKO_LOGISTICS_MEASUREMENTS_ENABLED=true`. Оба соответствующих
  client-флага и `SHUMEYKO_CLIENT_LOGIN_ENABLED` выключены; code defaults не
  считаются environment evidence.
- Новый immutable draft создан из сохраненных verified snapshots без повторного
  внешнего чтения после локальной runtime-ошибки. Measurement context имеет
  `partial`, source и mart reconciliation пройдены, blocking reasons пусты.
  Справочные удержания не включены в финансовые KPI до однозначной сверки.
- Staff read-only API и интерфейс F-4 приняты. Client-role получает HTTP 404;
  блок скрыт, а factor request не выполняется. Ошибок браузера и overflow на
  desktop/mobile не выявлено после CSS-hotfix.
- F-4 draft не публиковался. Общие publication blockers не скрыты и не
  переопределены. Factor-spec остается `accepted`: вся вторая очередь не
  завершена.
- Временные acceptance users деактивированы, пароли повторно сброшены, sessions,
  credential-файлы, screenshots и browser script удалены.
- Production symlink остается на
  `runtime-fcfc52b-tax-profile-configured-20260721`; production service,
  production/client factor flags и внешние интеграции этой работой не
  менялись.

# Operational evidence F-1 «Габариты» на test — 20 июля 2026 года

Проверка выполнена только на test-контуре из отдельной ветки
`codex/logistics-dimensions-end-to-end`. Финальная визуальная ревизия runtime —
`7b4d013`, immutable release —
`runtime-logistics-f1-dimensions-20260720-r2`. Public health подтвердил
`runtimeEnvironment=test`, build `20260720-logistics-f1-dimensions-v1`, schema
`2026_07_20_logistics_dimensions_context_v1` и status `ok`.

Environment evidence после restart:

- первая очередь логистики и factor master включены для staff;
- `SHUMEYKO_LOGISTICS_FACTORS_CLIENT_ENABLED=false`;
- code defaults обоих factor-флагов остаются `false`;
- production service, production symlink и клиентское factor-включение не
  менялись.

Из уже сохранённого verified full snapshot без повторных внешних API-вызовов
создан новый immutable draft. Dimension context записан с методикой
`wb-logistics-factors-v1`, имеет `partial`, а фактическое число mart rows
согласовано с context. `partial` вызван явными недоступными данными карточек и
не является publication blocker; draft не публиковался. Идентификаторы,
клиентские объёмы и значения карточек в evidence не перенесены.

Live API smoke подтвердил:

- staff `/api/me` разрешает F-1, `/logistics/dimensions` возвращает HTTP 200,
  `partial`, факторную методику, период и filter context, SQL-pagination и
  coverage полного фильтрованного среза;
- hash/raw поля отсутствуют, `measuredPenaltyAmount=null`, рекомендации не
  содержат денежного эффекта и используют только `limitation` и
  `data_unavailable`;
- client-role сохраняет HTTP 200 для основной логистики, но `/api/me` не
  разрешает factors, а factor API возвращает HTTP 404.

Browser smoke выполнен по прямому `#tables/logistics` на desktop 1440×900 и
mobile 390×844. Блок расположен после финансовой аналитики и перед рейтингом
товаров, показывает current-card snapshot как неисторический замер и не штраф;
на mobile строки преобразуются в подписанные карточки. Первый visual pass
выявил внутренний overflow последней колонки; CSS исправлен в `7b4d013`, runtime
пересобран, а повторный pass подтвердил отсутствие page/table overflow и
console/page/network errors. Под client-role блок скрыт и запрос dimensions не
выполняется. Временные acceptance users/sessions, credential-файл и локальные
screenshots после проверки удалены; в Git и Markdown они не попадали.

## Закрытие F-1 из `main`

PR №41 объединён обычным merge commit `834f818`. На push этого commit в
`main` оба обязательных GitHub Actions job созданы и завершены успешно:
`quality` и `tests`. Из точного merge commit собран immutable release
`runtime-logistics-f1-main-834f818-20260720` с `sourceDirty=false`, после чего
атомарно обновлён только test symlink и перезапущен только test web service.

После promotion public health повторно подтвердил `status=ok`, test contour,
совпадающие backend/static build
`20260720-logistics-f1-dimensions-v1` и schema
`2026_07_20_logistics_dimensions_context_v1`. Короткий live role smoke на
main-runtime подтвердил staff HTTP 200/`partial`, доступность основной
логистики для client-role и HTTP 404 factor API для client-role. Временные
пользователи и сессии удалены. Новый draft остался неопубликованным;
production и клиентское factor-включение не выполнялись.

Rollback F-1: вернуть factor master в `false`, перезапустить только test web и
при необходимости repoint test symlink на предыдущий immutable release.
Additive schema и immutable draft при этом не удаляются и не меняются.

# Operational evidence F-2 «Тарифы» на test — 21 июля 2026 года

Проверка выполнена только на test-контуре из ветки
`codex/logistics-tariffs-end-to-end`. Финальная принятая ревизия runtime —
`2480e41`, immutable release —
`runtime-logistics-f2-tariffs-2480e41-20260721`. Public health во время
приёмки подтвердил `runtimeEnvironment=test`, совпадающие backend/static build
`20260721-logistics-f2-tariffs-v2`, schema
`2026_07_21_logistics_tariffs_context_v1` и status `ok`.

На время приёмки на test были включены factor master и tariff master;
`SHUMEYKO_LOGISTICS_FACTORS_CLIENT_ENABLED=false` и
`SHUMEYKO_LOGISTICS_TARIFFS_CLIENT_ENABLED=false`. Code defaults всех
factor-флагов остались `false`. Production runtime и клиентское включение этой
работой не менялись.

Новый read-only full source refresh загрузил `wb_tariffs` и зафиксировал
verified manifest со статусом каждой запрошенной даты. Финальный расчётный шаг
первого worker-run остановился на недоступном относительном каталоге внутри
immutable release; после устранения только локальной runtime-причины новый
immutable draft был собран из тех же сохранённых snapshots без повторных
внешних API-вызовов. Перед сборкой raw manifest, flat hashes и row count были
проверены повторно.

Tariff context записан с методикой `wb-logistics-tariffs-v1` и состоянием
`partial`; фактическое число tariff mart rows согласовано с context. Недоступный
архив сохранён как явная оценка или отсутствие данных, без подстановки нулевых
ставок и без денежного эффекта. Draft не публиковался: publication gate оставил
его заблокированным до разбора обязательных review-состояний. Идентификаторы,
клиентские объёмы, названия складов, ставки и source hashes в evidence не
перенесены.

Live API smoke подтвердил:

- staff `/api/me` разрешает F-1 и F-2, `/logistics/tariffs` возвращает HTTP 200,
  `partial`, обе версии методики, factor snapshot, period/filter context,
  SQL-pagination, все разрешённые сортировки и coverage полного
  отфильтрованного среза;
- hash/raw identifiers отсутствуют, `financialEffect=null`, рекомендации не
  содержат денежного эффекта и используют только `limitation` и
  `data_unavailable`;
- client-role сохраняет HTTP 200 для основной логистики, но `/api/me` не
  разрешает factors/tariffs, factor API возвращает HTTP 404.

Browser smoke выполнен по прямому `#tables/logistics` на внутреннем test-unit
для desktop 1440×900 и mobile 390×844; public proxy отдельно подтверждён через
health, а его HTML Basic Auth не обходился и не читался. Блок F-2 расположен
после габаритов и перед рейтингом товаров. На mobile строки отображаются как
подписанные карточки внутри собственного вертикального скролла. Первый
визуальный pass выявил отсутствующий favicon и наложение карточек F-1 на F-2;
финальная ревизия устранила обе проблемы. Повторный pass подтвердил отсутствие
page/horizontal overflow и application console/page/network errors. Под
client-role блок скрыт и запрос tariffs не выполняется.

После приёмки временные sessions, credential-файл, browser runtime и screenshots
удалены; synthetic acceptance users деактивированы, а их пароли сброшены с
сохранением неизменяемого audit trail. Tariff test drop-in удалён, test symlink
возвращён на предшествующий параллельный immutable runtime. Additive schema и
неопубликованный F-2 draft сохранены; production и client enable не выполнялись.

# Operational evidence F-3 «Склады и направления» на test — 21 июля 2026 года

Проверка выполнена только на test-контуре из ветки
`codex/logistics-routes-end-to-end`, ревизия `b343592`. Для приёмки собран
immutable release `runtime-logistics-f3-routes-b343592-20260721`. Public health
во время проверки подтвердил `runtimeEnvironment=test`, совпадающие
backend/static build `20260721-logistics-f3-routes-v1`, additive schema
`2026_07_21_logistics_routes_context_v1` и `status=ok`. В PR №45 оба
обязательных job `quality` и `tests` завершились успешно.

На test временно были включены factor master и routes master. Оба client-флага
оставались `false`; code defaults не менялись. Client login включался отдельным
временным override только для role-проверки. Production runtime, production
configuration и клиентское включение факторов этой работой не изменялись.

Read-only full source refresh завершился состоянием `needs_review` из-за
явного неполного покрытия отдельных коллекций. Коллекция
`wb_supplier_sales` сохранена как `partial_source` с повторно проверенным
manifest, snapshot hash, flat hashes и row count. Стандартный worker template
не нашёл test-run в своём default-контексте до начала внешнего чтения, поэтому
тот же queued run был обработан синхронно в изолированном test environment;
повторного внешнего чтения не выполнялось.

Создан новый неопубликованный immutable draft. Route context записан с
методикой `wb-logistics-routes-v1` и состоянием `partial`; blocking reasons
пусты. Mart не пуст, фактическое число строк согласовано с context, а сумма
связанной и несвязанной логистики сверена с исходным логистическим срезом без
расхождения. Идентификаторы, клиентские объёмы, названия складов и направлений,
денежные значения и source hashes в evidence не перенесены.

Live API smoke подтвердил:

- staff `/api/me` разрешает analysis/factors/routes, основной logistics API и
  `/logistics/routes` возвращают HTTP 200; срез имеет `partial`, обе версии
  методики, factor snapshot, coverage полного фильтрованного среза,
  SQL-pagination и все разрешённые сортировки;
- route rows не раскрывают hash/raw identifiers; `financialEffect=null`, а
  рекомендации также не содержат денежного эффекта;
- client `/api/me` сохраняет основную логистику, но не разрешает factors/routes;
  factor API возвращает HTTP 404.

Browser smoke выполнен по прямому `#tables/logistics` на desktop 1440×900 и
mobile 390×844. Блок F-3 расположен после тарифов и перед рейтингом товаров,
строки на mobile имеют подписи, horizontal/page overflow отсутствует. Финальный
pass не выявил application console, page или network errors. Под client-role
блок скрыт, запрос `/logistics/routes` не выполняется. Public proxy отдельно
подтверждён через health; клиентские значения и browser screenshots не
сохранялись в Git или Markdown.

После приёмки synthetic users деактивированы, их пароли сброшены; credentials,
cookies, responses, screenshots и временный browser script удалены. Routes
drop-in и временный client login удалены, test symlink возвращён на
`runtime-fcfc52b-tax-profile-configured-20260721`. Additive schema и
неопубликованный F-3 draft сохранены. Production и client enable не
выполнялись.

## Post-merge promotion F-3 из `main` — 21 июля 2026 года

PR №45 слит в `main` squash-коммитом `a3b55af`. Из точного commit собран
immutable release `runtime-main-a3b55af-logistics-f3-20260721` с
`sourceDirty=false`; повторный запуск additive migration подтвердил schema
`2026_07_21_logistics_routes_context_v1`. Только test symlink атомарно
переключён на этот release и перезапущен только test web service.

Local и public test health подтвердили `status=ok`,
`runtimeEnvironment=test`, совпадающие backend/static build
`20260721-logistics-f3-routes-v1` и неактивный source refresh. Отдельный test
health timer завершился успешно. `SHUMEYKO_CLIENT_LOGIN_ENABLED=false`, factor
client flag остался `false`, а routes master/client overrides отсутствуют;
следовательно, F-3 после merge не включён ни для staff, ни для client без
отдельного rollout-решения.

Production symlink остался на
`runtime-fcfc52b-tax-profile-configured-20260721`; production local health
сохранил `status=ok`, production environment и прежние совпадающие
backend/static build. Новый report не публиковался, production/client flags и
внешние интеграции не менялись.

# Operational evidence F-4 «Замеры/штрафы» на test — 21 июля 2026 года

F-4 влит в `main` через PR №49 squash-коммитом `90420d6`. Обязательные GitHub
Actions job завершились успешно: `quality` за 1 минуту 1 секунду и `tests` за
23 минуты 10 секунд. Обнаруженное при визуальной приемке перекрытие длинного
названия товара с соседней desktop-колонкой исправлено в PR №50, слитом
squash-коммитом `fe0f229`; повторные `quality` и `tests` прошли за 1 минуту
16 секунд и 19 минут 47 секунд соответственно.

Из точного `fe0f229` собран immutable release
`runtime-main-fe0f229-logistics-f4-v2-20260721` с `sourceDirty=false`.
Additive migration повторно применена идемпотентно, после чего атомарно
переключен только test symlink и перезапущен только test web service. Финальный
health подтвердил `status=ok`, `runtimeEnvironment=test`, одинаковый
backend/static build `20260721-logistics-f4-measurements-v2` и schema
`2026_07_21_logistics_measurements_context_v1`.

На test включены factor master и measurement master. Factor- и
measurement-client flags оставлены `false`; штатный client login после
приемки также подтвержден как выключенный фактическим HTTP 401 при корректном
пароле синтетической client-роли. Production configuration и production
service не изменялись.

Read-only full source refresh загрузил обе требуемые F-4 коллекции и сохранил
verified snapshots. Первый внешний проход был остановлен транзитной ошибкой 1C
до завершения; успешный повтор сохранил источники, но materialization уперлась
в недоступный относительный путь immutable runtime. Новый draft затем собран
из тех же сохраненных snapshots без повторного внешнего чтения. Перед сборкой
повторно проверены безопасные пути, manifest, hashes, row count, tenant scope и
отсутствие DB/file ambiguity.

Создан новый неопубликованный immutable draft со статусом `needs_review`.
Measurement context записан с методикой `wb-logistics-measurements-v1` и
состоянием `partial`; provider endpoint total и mart row count согласованы,
blocking reasons пусты. События, не имеющие однозначной финансовой сверки,
остались справочными: удержание, отмена и чистая сумма не добавлены в расходы,
прибыль или иные финансовые KPI. Общие publication blockers сохранены; F-4 не
переопределял их. Идентификаторы, клиентские объемы, товарные значения,
денежные суммы и source hashes в evidence не перенесены.

Live API и browser acceptance подтвердили:

- staff read-only API возвращает HTTP 200, `partial`, обе версии методики,
  source coverage, filter context, SQL-pagination, разрешенные сортировки и
  coverage полного фильтрованного среза;
- raw/hash identifiers отсутствуют, рекомендации не создают финансовый эффект,
  а сигнал и справочные суммы не трактуются как подтвержденный штраф;
- client-role получает HTTP 404, блок скрыт и запрос factor API не выполняется;
- прямой `#tables/logistics` прошел на desktop 1440×900 и mobile 390×844 без
  horizontal/page overflow и application console/page/network errors;
- повторная визуальная проверка после PR №50 подтвердила перенос длинных
  названий без перекрытия соседних колонок; mobile-строки отображаются как
  подписанные карточки.

После проверки временный client-login override удален. Synthetic acceptance
users деактивированы, их пароли повторно сброшены, sessions, credential-файлы,
browser script и screenshots удалены. Существовавшие source-refresh cache
каталоги не удалялись, поскольку их принадлежность только этой приемке не была
доказана. Test остается на F-4 v2 со staff-only flags; production symlink
остается на `runtime-fcfc52b-tax-profile-configured-20260721`. Factor-spec
остается `accepted`; production, client enable и публикация draft не
выполнялись.

Rollback F-4: вернуть measurement master, а при необходимости factor master в
`false`, перезапустить только test web и repoint test symlink на предыдущий
immutable release. Additive schema, snapshots и неопубликованный immutable
draft при этом не удалять и не перезаписывать.

# Последнее UX-решение

Пользователь подтвердил, что текущая структура интерфейса непонятна: она
показывает много технически верных данных, но не отвечает в первом экране на
вопросы «сколько потеряли, почему и что делать». При этом отдельный
верхнеуровневый пункт «Логистика» признан избыточным.

Целевое направление для следующего spec-first этапа:

1. Переименовать раздел `Таблицы` в `Аналитика и таблицы` или `Аналитика`.
2. Внутри использовать явные вложенные сценарии: `Сводка`, `Товары`,
   `Логистика`, `Возвраты`, `Расходы WB`, `Исходные данные`.
3. На главной карточке расходов дать действие `Разобрать логистику`, ведущее
   напрямую в `#tables/logistics`.
4. В логистическом сценарии сначала показывать итог, влияние в рублях и список
   `проблема -> сумма -> причина/ограничение -> действие`; детальные цепочки и
   технические поля убирать во второй уровень.
5. Не смешивать подтвержденные причины возвратов с гипотезами. Показывать
   отдельное покрытие: `причина получена` / `причина недоступна`.
6. Сохранить текущий визуальный язык и компоненты; это перестройка information
   architecture, а не полный редизайн.

Перед frontend-изменениями нужен визуальный target и проверяемые acceptance
criteria. Текущий production/test URL пока использует рабочий deep-link
`#logistics`; `#tables/logistics` — согласованное направление, а не уже
реализованный маршрут.

# Результат spec-first этапа

- Accepted logistics spec закрепляет вложенный сценарий, answer-first summary,
  state matrix `ready`/`partial`/`needs_rebuild`/`blocked`/empty/error и
  desktop/mobile acceptance criteria без изменения `wb-logistics-v4`.
- Accepted web spec закрепляет единый sidebar entry, stable nested order,
  безопасный fallback при выключенном role/feature flag, сохранение
  разрешенного draft и глобального среза, Back/Forward и focus transfer.
- Синтетический visual target подготовлен в
  `docs/design/wb-logistics-v4-analytics-target.html` на реальных цветовых
  токенах и локальных иконках кабинета.
- Статический аудит уточнил семантику: общий расход логистики не называется
  целиком устранимой потерей; пересекающиеся зоны проверки не складываются;
  строки различают `Факт`, `Ограничение` и `Качество данных`; mobile не скрывает
  кабинет, организацию, период или схему.
- На исходном spec-first этапе screenshot-приемка не выполнялась. Для текущего
  test-rollout она позднее завершена временным browser runtime; frontend,
  production и feature flags при визуальной проверке не изменялись.

# Причины возвратов: что установлено

- Текущий реальный расчет использует WB Finance. В его загруженном контракте
  есть финансовый факт возврата и связанные суммы/операции, но нет объяснения
  покупателя; интерфейс правильно не придумывает причину.
- Отдельный read-only метод WB
  `GET seller-analytics-api.wildberries.ru/api/v1/analytics/goods-return`
  содержит поле `reason`, но описывает возвраты и перемещения товара продавцу,
  а не универсальную причину каждого финансового возврата; один запрос
  ограничен периодом до 31 дня.
- Отдельный read-only метод
  `GET returns-api.wildberries.ru/api/v1/claims` содержит `user_comment`,
  статусы, media и `srid`, но возвращает заявки покупателей только за текущие
  14 дней. `is_archive` в актуальном OpenAPI — boolean и выбирает состояние
  заявки; документированного глубокого архива нет.
- В `main` есть prework read-only goods-return client/export и файловый вызов
  source refresh, но нет зарегистрированного snapshot, claims connector,
  context/mart/API/UI или Finance join. Это не end-to-end реализация.
- Accepted F-5 spec требует boolean-only R-0 доступов/coverage и exact
  `(cabinet, srid, nm_id)` join. `goods-return.reason` и факт наличия
  `claims.user_comment` не взаимозаменяемы; raw комментарии и media не попадают
  в mart/API/AI.

# Реализованные правила v4

1. Source-, report- и результирующие строки проверяются в tenant/client scope.
2. Persistence повторно проверяет владельцев кабинета и организации в БД и
   связь кабинета с указанной организацией.
3. Non-object JSON, поврежденные обязательные даты, числа, схемы и dimensions
   блокируют gate; silent fallback к нулю, началу периода или FBO запрещен.
4. Revision ownership определяется календарным source window: current run,
   дневной lineage, затем base snapshot. Конфликт владельцев блокирует gate.
5. Revision conflict и input hash используют canonical hash фактического
   payload. Несовпадение с сохраненным raw hash блокирует расчет.
6. Reconciliation выполняется source -> order -> SKU -> ReportUnitRow глобально
   и по неделе, кабинету, организации, схеме и товару с допуском `0,01 руб.`.
7. Повторная запись logistics-context для того же `report_id` запрещена даже
   при идентичном input hash; нужен новый report run.
8. Некорректный API-период возвращает HTTP 400 `invalid_logistics_period`.
9. Для части недели логистика точная, а недельные финансовые KPI равны `null`
   с `financialMetricStatus=not_available_partial_week`.
10. `previous_report_period` используется только для возвратной цепочки;
    старый forward-заказ получает `order_before_report_period`.
11. Рекомендации и classification coverage рассчитываются SQL-запросами по
    полному выбранному срезу, а не из top-10 глобального рейтинга.
12. Raw payload и внешние идентификаторы заказов не передаются интерфейсу и AI.

# Основные файлы

- `src/wb_unit_economics/logistics_analysis.py` — чистый расчет, классификация,
  hash, reconciliation и order/SKU-агрегация.
- `src/wb_unit_economics/web/source_refresh.py` — выбор исходных ревизий,
  canonical payload hash и построение нового logistics-context.
- `src/wb_unit_economics/web/repository.py` — immutable persistence,
  tenant/cabinet/company validation, readiness, API payload и рекомендации.
- `src/wb_unit_economics/web/app.py` — три endpoint и строгий period-validator.
- `src/wb_unit_economics/web/models.py`, `web/database.py`,
  `sql/postgres_schema.sql` — additive schema migration v4 и индексы.
- `src/wb_unit_economics/web/ai.py` — агрегатный AI digest без raw данных.
- `src/wb_unit_economics/web/static/` — staff-only раздел и статусы периода.
- `tests/test_logistics_analysis.py`, `tests/test_source_refresh.py`,
  `tests/test_web_app.py`, `tests/test_db_first_publication.py` — расчетные,
  source, API/UI, tenant-isolation и migration проверки.

# Последний дополнительный hardening

После повторного аудита исправлены три дефекта:

- сохранение чужого cabinet/company при формально правильных tenant/client;
- доверие сохраненному `raw_payload_hash`, позволявшее скрыть разные payload;
- молчаливое принятие повторного импорта при совпавшем input hash.

Добавлены тесты на foreign cabinet/company, stale одинаковый hash для разных
payload и повторную запись context.

# Проверки

Полный прогон исходного исправления `d24d356`:

```text
773 passed, 5 warnings in 516.10s
```

Пять warnings — сторонние deprecation warnings FastAPI/TestClient и ChatKit;
они не блокируют текущий пакет.

Также успешно выполнены документационные валидаторы, Ruff, целевые
logistics/routing/database/web tests и проверка real snapshot. Live API smoke
на test вернул HTTP 200 для `/api/me`, summary, products и staff orders; неверный
период вернул HTTP 400. Все contract-checks fail-closed прошли.

Команды для воспроизведения статической части на ревизии `d24d356`:

```bash
.venv/bin/ruff check .
node --check src/wb_unit_economics/web/static/app.js
.venv/bin/python scripts/generate_web_api_reference.py --check
.venv/bin/python scripts/validate_docs_manifest.py
.venv/bin/python scripts/validate_llm_docs.py
.venv/bin/python scripts/validate_specs.py docs/specs/wb-logistics-cost-analysis-implementation.md
.venv/bin/python scripts/validate_documentation_contracts.py
.venv/bin/python scripts/docs_route.py --check-generated
.venv/bin/python scripts/validate_no_secrets.py
git diff --check
```

PR №16 объединен в `main` merge-коммитом `3773ed5`. Обязательные GitHub Actions
`quality` и `tests` успешно завершились как на PR, так и повторно на merge-
коммите. После test promotion schema v5, runtime health, staff/client API и
fail-closed KPI smoke успешно повторены.

PR №17 с operational evidence объединен в `main` merge-коммитом `7747a4d`;
повторный main CI завершился успешно. После этого desktop/mobile visual smoke
на test также прошел; временная staff-сессия и browser runtime после проверки
удаляются, клиентские агрегаты в документацию не переносятся.

# Рабочее дерево

Исправление было подготовлено в отдельном clean worktree; несвязанные изменения
основного рабочего дерева в PR №16 не вошли. PR объединен в `main`. Operational
evidence test-rollout фиксировать отдельным docs-only change, не перенося его
через dirty worktree.

# Итог ownership/diff-аудита на 16 июля 2026 года

Аудит выполнен read-only относительно ветки
`codex/incremental-source-refresh-rollout` на коммите `fad6641`. В рабочем
дереве 24 измененных и 5 новых файлов. Staging, commit, push и deployment не
выполнялись.

Текущая ветка на 28 коммитов впереди `main` и на 4 локальных коммита впереди
`origin/codex/incremental-source-refresh-rollout`. Поэтому прямой PR в `main`
не будет изолированным PR только для hardening v4: он захватит всю предыдущую
цепочку. Для отдельного PR нужен base, в котором уже присутствуют предыдущие
коммиты WB-логистики и четыре локальных commit текущей ветки, либо отдельная
согласованная перебазировка всей цепочки.

## Можно брать целиком в логистический commit

- `docs/index.md`;
- `docs/manifest.yml`;
- `docs/runbooks/web-cabinet-operations.md`;
- `docs/runbooks/wb-logistics-v4-continuation.md`;
- `docs/specs/wb-logistics-cost-analysis-implementation.md`;
- `sql/postgres_schema.sql`;
- `src/wb_unit_economics/logistics_analysis.py`;
- `src/wb_unit_economics/web/ai.py`;
- `src/wb_unit_economics/web/database.py`;
- `src/wb_unit_economics/web/models.py`;
- `tests/test_ai_analyst.py`;
- `tests/test_db_first_publication.py`;
- `tests/test_logistics_analysis.py`.

## Нужен выбор только логистических hunks

- `docs/changelogs/web-cabinet.md`: брать записи v2.50, v2.51 и v2.52; v2.49
  относится к отдельному мастеру формирования отчета;
- `src/wb_unit_economics/web/app.py`: брать period-validator, три logistics
  endpoint и cache-busting build id; не смешивать с несогласованным вариантом
  build id другого UI-пакета;
- `src/wb_unit_economics/web/repository.py`: брать logistics persistence,
  scope validation, SQL-срезы, readiness и рекомендации; не брать механическое
  форматирование налоговых функций и посторонних текстов;
- `src/wb_unit_economics/web/source_refresh.py`: брать logistics imports,
  DB-first gate, обязательный context, lineage/revision selection и построение
  v4; не брать форматирование существующего incremental source-refresh кода;
- `src/wb_unit_economics/web/static/app.js`: брать только state и функции
  `loadLogisticsAnalysis`, `renderLogisticsWorkspace`,
  `renderLogisticsProducts`, `openLogisticsOrders`,
  `renderLogisticsOrders`, `closeLogisticsOrders` и logistics-ветку заголовка;
  изменения report wizard и client-report scope относятся к отдельной работе;
- `tests/test_source_refresh.py`: брать изменения logistics fixture и новые
  tests gate/revision/scope; не брать форматирование incremental tests;
- `tests/test_web_app.py`: брать logistics imports, helpers и API, isolation,
  immutability, publication-blocker, SQL slice/recommendation tests, а также
  согласованный logistics build id; остальные formatter/report-wizard hunks
  исключить.

Отдельный коммит `f458fac` ветки
`codex/accounting-canary-report-wizard` подтверждает происхождение изменений
мастера формирования отчета. Если он уже находится в base будущего
логистического commit, допустим согласованный общий build id
`20260716-report-wizard-clarity-v1-logistics-v4`. Если логистический commit
строится непосредственно от `fad6641`, нужно использовать отдельный
logistics-only cache buster и согласованно обновить `WEB_BUILD_ID`, meta build
id, query для `app.js` и соответствующие тесты.

## Не включать в логистический commit

- `deploy/systemd/shumeiko-web-backup.service`;
- `deploy/systemd/shumeiko-source-refresh-retention-maintenance.service`;
- `deploy/systemd/shumeiko-source-refresh-retention-maintenance.timer`;
- `docs/specs/source-refresh-database-retention.md`;
- `scripts/run_source_refresh_retention_maintenance.py`;
- `tests/test_source_refresh_retention_maintenance.py`;
- `docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md`;
- report-wizard hunks в `src/wb_unit_economics/web/static/index.html`,
  `src/wb_unit_economics/web/static/styles.css`,
  `src/wb_unit_economics/web/static/app.js` и `tests/test_web_app.py`;
- механические formatter-only hunks вне logistics-кода.

## Безопасный порядок формирования commit/PR

1. Выбрать base, который уже содержит предыдущую WB-логистику и необходимые
   source-refresh commits. Для dependent PR сначала опубликовать согласованный
   base; не направлять текущую 28-коммитную ветку в `main` под видом v4-only.
2. Сформировать отдельный index/patch по спискам выше, не меняя и не откатывая
   остальные файлы рабочего дерева.
3. Проверить staged diff отдельно от unstaged: в нем не должно быть retention,
   report-wizard или formatter-only изменений.
4. Повторить полный набор проверок из раздела `Проверки` на точном содержимом
   будущего commit, а не только на объединенном dirty worktree.
5. Только после этого создавать commit и dependent PR. Test-rollout остается
   отдельным этапом и требует явного разрешения.

# Исправления по bug-аудиту

После ownership/diff-аудита исправлены шесть подтверждённых дефектов без
deployment и без write-операций во внешние системы:

- provider `rrdId` теперь должен точно совпадать с сохранённым
  `source_row_id`; несовпадение блокирует gate как
  `source_identity_mismatch`;
- текстовый поиск товара сначала выбирает канонические `productRef` в order
  mart, затем агрегирует все их order/SKU-строки и цепочки, включая строки с
  другим историческим названием;
- для неполной недели `profitEffectAmount` и рейтинг по влиянию на прибыль не
  публикуются;
- slice/product quality учитывает неполные order/SKU rows, показывает partial
  и формирует отдельную рекомендацию проверки данных;
- интерфейс использует `total`, `offset` и `limit` для перехода по страницам
  рейтинга товаров и обезличенных цепочек;
- влияние на прибыль показывается абсолютной суммой с явным направлением, без
  необъяснённого отрицательного числа.

Проверки после исправлений:

- `45 passed, 247 deselected` в расширенном logistics-срезе
  `test_logistics_analysis`, `test_source_refresh`, `test_web_app`,
  `test_db_first_publication`, `test_ai_analyst`;
- `node --check` и Ruff для изменённого Python/JS-кода прошли;
- spec, docs manifest, LLM links, documentation contracts и OpenAPI inventory
  синхронизированы;
- `git diff --check` прошёл.

Повторный bug-аудит 17 июля дополнительно исправил порядок рекомендаций по
`priority` и регрессию поиска при нескольких названиях одного `productRef`.
После исправлений полный набор завершён результатом `723 passed`; пять
предупреждений относятся к deprecation в Starlette/ChatKit dependencies.

# Следующий этап

Обновление 2026-07-22: F-1 «Габариты», F-2 «Тарифы», F-3 «Склады и
направления» и F-4 «Замеры и удержания» приняты на staff-only test. Для F-5
«Причины возвратов» принят отдельный spec-first контракт. Следующий разрешённый
data-шаг после boolean-only R-0I/R-0L — новый immutable report из однозначного
verified Finance storage и повтор того же identity evidence. Source schema
подтверждена, но выбранный lineage имеет DB/file ambiguity, а newest-first R-0L
не нашёл пригодного существующего report: `newReportRequired=true`, exact
crosswalk не оценён как verified и `implementationGate=false`. R-1…R-5 не
начинаются. Создание report требует отдельного operational решения; R-0L не
разрешает production migration/runtime rollout или retention deletion.
Factor-spec остаётся `accepted`, потому что F-5, объединённая staff-приёмка и
client/production решения не завершены. Общий операционный чеклист —
`docs/runbooks/wb-logistics-factors-probe.md`. Задача
`monthly_reconciliation_unresolved` остаётся advisory (PR №22).

1. Разобрать сохраненную контрольную задачу
   `monthly_reconciliation_unresolved`; не скрывать ее из readiness и не
   пересобирать текущий immutable report на месте.
2. Отдельно согласовать безопасный способ получить новый immutable report из
   однозначно выбранного Finance storage без DB/file ambiguity. Не применять
   production migrations/runtime rollout и не завершать retention deletion без
   их собственных approval, backup и rollback prerequisites. После создания
   повторить готовый `--mode r0-identity` на том же report window. Выводить
   только boolean overlap; не разрешать одиночный identifier, product-only join
   или ручной выбор одной из конфликтующих копий.
3. Для повторной клиентской приемки использовать текущую ссылку вида
   `/cabinet?client_id=<authorized_client>&report_id=<current_report>#tables/logistics`;
   конкретные идентификаторы брать из локального разрешенного операционного
   контекста. Для финансовых KPI выбирать границы полных недель внутри периода
   отчета; на неполных границах логистика точная, а недельные финансовые KPI
   намеренно `null`.

# Что не входит в текущий этап

- Excel-экспорт анализа логистики;
- финансовое включение F-4 удержаний без exact reconciliation с Finance;
- маршрутная оптимизация и географический калькулятор;
- тарифный калькулятор;
- калькулятор маржинального дохода;
- production client rollout;
- любые write-операции во внешние системы.
