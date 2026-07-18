---
title: "Operational state WB-логистики"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "agent", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-logistics-cost-analysis-implementation.md"
updated_at: "2026-07-18"
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

Исправление чтения больших file-authoritative WB Finance snapshot включено в
`main` merge-коммитом `3773ed5` и развернуто только на test в immutable release
`runtime-3773ed5-logistics-file-reader-20260718`. Свежий full refresh с
разрешенными клиентом read-only интеграциями выполнен; исходный raw snapshot не
изменялся и повторно использован для нового immutable recovery-draft без новых
внешних API-вызовов. Draft не опубликован и проверен через live staff и
client-role API. Production, текущая публикация и клиентский флаг не менялись.

# Текст для нового чата

```text
Продолжи работу в /opt/shumeyko-partners-wb-unit-economics по WB-логистике v5.
Сначала запусти compact route для scope `logistics-cost-analysis` и проверь
операционное состояние в этом runbook. Исправление file-authoritative snapshot
включено в main merge-коммитом 3773ed5. На test развернут immutable release
runtime-3773ed5-logistics-file-reader-20260718, master-флаг включен только для
staff, клиентский флаг выключен. Свежий full read-only refresh выполнен с
клиентскими интеграциями. Из его неизмененного raw snapshot создан отдельный
immutable recovery-draft без повторных внешних запросов и без публикации.
Logistics gate ready; summary корректно возвращает partial и
not_available_missing_profit_link: финансовые KPI/rankings null/empty, точная
логистика и обезличенные order/product данные доступны. Live staff API smoke
прошел; инвертированный период отклонен HTTP 400. Идентификаторы и клиентские
агрегаты не хранятся в Markdown. Live client-role smoke подтвердил client flag
false и HTTP 404 для logistics summary и staff orders; временный пользователь и
сессии удалены. Production и текущую публикацию не менять. Следующий шаг —
ручная browser-приемка desktop/mobile, затем отдельное разрешение на client flag.
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
  `3773ed5`; test указывает на immutable release
  `runtime-3773ed5-logistics-file-reader-20260718`. Production остался на
  отдельно проверенном release
  `runtime-6368dcf-global-table-sorting-20260718`; test promotion не менял
  production symlink или service.
- На test `SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true` и master-флаг логистики
  применены через отдельный systemd override; клиентский флаг остается
  `false`. Code defaults по-прежнему `false/false` и не считаются environment
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
  `ready`, методику `wb-logistics-v5`, report остается `draft` и не заменяет
  текущую публикацию. Идентификаторы и клиентские объемы не фиксируются в Git
  или Markdown.
- Live staff API вернул `partial` и
  `not_available_missing_profit_link`: точная логистика, products и staff-only
  orders доступны, финансовые KPI равны `null`, финансовые рейтинги пусты.
  Инвертированный период отклоняется HTTP 400. Одноразовая staff-сессия после
  smoke удалена; `/api/me` подтверждает master flag `true` и client flag
  `false`, а regression tests покрывают client-role 404.
- Live client-role smoke на merge-release вернул HTTP 200 для `/api/me` и HTTP
  404 для logistics summary и staff-only orders. Frontend содержит явное
  сообщение `Финансовая связь с отчётом отсутствует`; временный client-user и
  обе smoke-сессии после проверки удалены. Полноценный screenshot-аудит не
  выполнен: на host нет доступного browser runtime.
- Public health test-контура отдает build
  `20260718-logistics-v5-global-table-sorting-v1`, schema
  `2026_07_18_logistics_profit_link_v5` и `runtimeEnvironment=test`; health
  timer завершился `success`.
- Production, текущий опубликованный report и client flag не менялись. Любой
  последующий rollout требует повторной проверки environment evidence и
  отдельного разрешения.

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
- В текущем Codex-сеансе нет доступного in-app browser, поэтому screenshot-
  приемка desktop/mobile не выполнена и не считается пройденной. Runtime
  frontend, feature flags, test deployment и production этим этапом не
  изменялись.

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

1. Выполнить ручную browser-приемку test на desktop 1440×900 и mobile 390×844:
   `null` не выглядит как ноль, причина недоступности финансов видима, нет
   горизонтального overflow, keyboard/focus и deep-link работают. Текущий host
   не имеет browser runtime, поэтому этот пункт остается открытым.
2. Только после визуальной приемки и отдельного разрешения включать client flag
   на test. Повторить client-role summary/products smoke; staff orders должны
   остаться недоступными. Production и текущую публикацию не менять.
3. Отдельно подготовить spec/probe для read-only `goods-return` и `claims`:
   доступ токена, retention, coverage, join по `srid`/заказу и явные unmatched
   статусы. Не смешивать этот источник с уже готовым Finance gate.
4. До завершения клиентской приемки использовать текущую staff-ссылку вида
   `/cabinet?client_id=<authorized_client>&report_id=<authorized_draft>#logistics`;
   конкретные идентификаторы брать из локального разрешенного операционного
   контекста. Для финансовых KPI выбирать границы полных недель внутри периода
   отчета; на неполных границах логистика точная, а недельные финансовые KPI
   намеренно `null`.

# Что не входит в текущий этап

- Excel-экспорт анализа логистики;
- габариты и контрольные замеры;
- маршруты и локализация складов;
- тарифный калькулятор;
- калькулятор маржинального дохода;
- клиентский rollout;
- любые write-операции во внешние системы.
