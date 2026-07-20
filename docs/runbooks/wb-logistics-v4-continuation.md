---
title: "Operational state WB-логистики"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "agent", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-logistics-cost-analysis-implementation.md"
updated_at: "2026-07-20"
---

# Назначение

Этот handoff нужен для продолжения работы в новом чате. Он не заменяет
accepted-спецификацию. При расхождении следовать `AGENTS.md`,
`docs/manifest.yml` и
`docs/specs/wb-logistics-cost-analysis-implementation.md`.

Последнее записанное operational evidence датировано **18 июля 2026 года**.
Перед любым утверждением о текущих feature flags, runtime, gate или rollout
обязательно повторно проверить соответствующую среду; приведенное ниже
состояние не является доказательством на более позднюю дату. Code defaults
`false/false` описывают только поведение без конфигурации и не подтверждают
фактическое состояние test или production.

Проверенный immutable recovery-draft из свежего full read-only refresh
опубликован как текущий test-report после отдельного разрешения. Публикация
выполнена штатным audited-механизмом; общий blocker
`monthly_reconciliation_unresolved` сохранен как контрольная задача и не скрыт.
На test master- и клиентский флаги включены, развернут immutable release
`runtime-fa020db-logistics-client-ui-20260718`. Production остается на
`runtime-6368dcf-global-table-sorting-20260718`, клиентский флаг там выключен.

# Текст для нового чата

```text
Продолжи работу в /opt/shumeyko-partners-wb-unit-economics по WB-логистике v5.
Сначала запусти compact route для scope `logistics-cost-analysis` и проверь
операционное состояние в этом runbook. На test развернут immutable release
runtime-fa020db-logistics-client-ui-20260718, master- и клиентский флаги
включены. Проверенный recovery-draft свежего full read-only refresh опубликован
как current через audited publish-with-tasks; blocker
monthly_reconciliation_unresolved сохранен. Client-role summary/products
возвращают HTTP 200, dataStatus ready, sliceStatus partial и
not_available_missing_profit_link: финансовые KPI/rankings null/empty, точная
логистика и product rows доступны. Staff-only orders и оставшийся старый draft
возвращают HTTP 404. Desktop/mobile deep-link #tables/logistics прошел без
дополнительного клика, application console/page/network errors и overflow.
Временные пользователи и сессии удалены. Production не менять без отдельного
разрешения; его runtime и client flag остались прежними.
```

# Текущее состояние

- Расчетная методика нового test-draft: `wb-logistics-v5`.
- Формула ключа: `wb-order-product-v1`.
- Поддерживается только WB.
- Реализованы order/SKU-витрины, readiness-context, три read-only API,
  staff-only интерфейс, SQL-рекомендации и безопасный AI digest.
- Контексты v1-v4 и несовместимая версия ключа возвращают `needs_rebuild`.
- `SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=false` по умолчанию.
- `SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED=false` по умолчанию.
- Исправление file-authoritative snapshot включено в `main` merge-коммитом
  `3773ed5`; клиентский deep-link hardening включен merge-коммитом `fa020db`.
  Test указывает на immutable release
  `runtime-fa020db-logistics-client-ui-20260718`. Production остался на
  отдельно проверенном release
  `runtime-6368dcf-global-table-sorting-20260718`; test promotion не менял
  production symlink или service.
- На test `SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true` и master-флаг логистики
  применены через отдельный systemd override; после визуальной приемки и
  отдельного разрешения клиентский флаг переключен в `true`. Code defaults
  по-прежнему `false/false` и не считаются environment
  evidence.
- С разрешенными клиентом read-only интеграциями выполнен новый full refresh в
  test. Обязательные внешние чтения завершились; raw snapshot и его manifest
  сохранены до нормализации. Одна 1C-конфигурация из локального environment была
  неактуальна, поэтому использована уже сохраненная защищенная tenant-интеграция
  только в памяти процесса; секреты не копировались в Git, Markdown или вывод.
- Первый свежий draft оказался `blocked`: крупная коллекция WB Finance была
  корректно сохранена как `skipped_large_snapshot` с авторитетными raw-файлами,
  но logistics selector читал только строки БД. Это подтвержденный storage gap,
  а не отсутствие данных источника.
- Коммит `d24d356` добавил потоковое чтение только для повторно проверенного
  `file_authoritative`/`skipped_large_snapshot`: путь обязан оставаться внутри
  run root, manifest/hash/row count перепроверяются, а одновременные DB- и
  file-строки блокируются как неоднозначность.
- Из того же неизмененного свежего snapshot создан новый immutable recovery-
  draft без внешних API-вызовов и перезаписи старого report run. Context имеет
  `ready`, методику `wb-logistics-v5`. После отдельного разрешения report
  опубликован как current через audited publish-with-tasks; blocker
  `monthly_reconciliation_unresolved` сохранен как контрольная задача.
  Идентификаторы и клиентские объемы не фиксируются в Git или Markdown.
- Live staff API вернул `partial` и
  `not_available_missing_profit_link`: точная логистика, products и staff-only
  orders доступны, финансовые KPI равны `null`, финансовые рейтинги пусты.
  Инвертированный период отклоняется HTTP 400. Одноразовая staff-сессия после
  smoke удалена. После rollout `/api/me` подтверждает master flag `true` и
  client flag `true`.
- Live client-role smoke после публикации вернул HTTP 200 для `/api/me`,
  logistics summary и products текущего v5-report: `dataStatus=ready`,
  `sliceStatus=partial`, финансовый статус
  `not_available_missing_profit_link`, финансовые KPI `null`, рейтинги пусты,
  product rows доступны. Staff-only orders и оставшийся старый draft возвращают
  HTTP 404. Временный client-user и smoke-сессия удалены.
- Временный Playwright/Chromium browser runtime использован только вне
  репозитория для desktop 1440×900 и mobile 390×844 приемки. После исправления
  гонки начальной загрузки deep-link `#tables/logistics` стабилен без
  дополнительного клика; staff-only `client-draft` из client-role не
  запрашивается. Focus transfer, отсутствие global overflow, именованные
  controls, `null -> —`, видимая причина недоступности финансов и product rows
  подтверждены; application console/page/network errors отсутствуют. На первом
  mobile viewport warning находится ниже global filters/navigation, но доступен
  обычной прокруткой без отдельного раскрытия. Снимки остаются локальным
  operational evidence и не добавляются в Git или Markdown.
- Public health test-контура отдает build
  `20260718-logistics-v5-global-table-sorting-v1`, schema
  `2026_07_18_logistics_profit_link_v5` и `runtimeEnvironment=test`; health
  timer завершился `success`.
- Production и текущий опубликованный report не менялись; production client
  flag остается выключенным. Публикация v5 draft или production rollout требуют
  повторной проверки environment evidence и отдельного разрешения.

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
  статусы, media и `srid`, но возвращает заявки покупателей только за
  ограниченное актуальное окно (в проверенной документации — 14 дней), а не
  полный исторический квартал.
- До реализации перепроверить актуальные официальные WB OpenAPI Reports и
  User Communication, выполнить безопасный probe доступов/coverage и
  зафиксировать join/reconciliation. Не считать `goods-return.reason` и
  `claims.user_comment` взаимозаменяемыми.

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

Обновление 2026-07-20: F-1 «Габариты» принят на staff-only test. Factor-spec
остаётся `accepted`, потому что вторая очередь ещё не завершена. Следующие
отдельные implementation slices — F-2 тарифы, F-3 маршруты и F-4 фактические
замеры/штрафы; каждый требует собственного source gate и test-rollout. Общий
операционный чеклист проверки источников —
`docs/runbooks/wb-logistics-factors-probe.md`. Задача
`monthly_reconciliation_unresolved` остаётся advisory (PR №22).

1. Разобрать сохраненную контрольную задачу
   `monthly_reconciliation_unresolved`; не скрывать ее из readiness и не
   пересобирать текущий immutable report на месте.
2. Отдельно подготовить spec/probe для read-only `goods-return` и `claims`:
   доступ токена, retention, coverage, join по `srid`/заказу и явные unmatched
   статусы. Не смешивать этот источник с уже готовым Finance gate.
3. Для повторной клиентской приемки использовать текущую ссылку вида
   `/cabinet?client_id=<authorized_client>&report_id=<current_report>#tables/logistics`;
   конкретные идентификаторы брать из локального разрешенного операционного
   контекста. Для финансовых KPI выбирать границы полных недель внутри периода
   отчета; на неполных границах логистика точная, а недельные финансовые KPI
   намеренно `null`.

# Что не входит в текущий этап

- Excel-экспорт анализа логистики;
- фактические контрольные замеры и штрафы;
- маршруты и локализация складов;
- тарифный калькулятор;
- калькулятор маржинального дохода;
- production client rollout;
- любые write-операции во внешние системы.
