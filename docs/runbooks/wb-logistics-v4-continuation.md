---
title: "Operational state WB-логистики"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "agent", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-logistics-cost-analysis-implementation.md"
updated_at: "2026-07-17"
---

# Назначение

Этот handoff нужен для продолжения работы в новом чате. Он не заменяет
accepted-спецификацию. При расхождении следовать `AGENTS.md`,
`docs/manifest.yml` и
`docs/specs/wb-logistics-cost-analysis-implementation.md`.

Последнее записанное operational evidence датировано **17 июля 2026 года**.
Перед любым утверждением о текущих feature flags, runtime, gate или rollout
обязательно повторно проверить соответствующую среду; приведенное ниже
состояние не является доказательством на более позднюю дату. Code defaults
`false/false` описывают только поведение без конфигурации и не подтверждают
фактическое состояние test или production.

Принятая методика v5 и миграция из текущего change set еще не развернуты этим
runbook. После merge для них нужен отдельный test-rollout: применить migration,
создать новый immutable v5 draft и повторно проверить gate/KPI/UI. Production и
клиентский флаг без отдельного разрешения не включать.

# Текст для нового чата

```text
Продолжи работу в /opt/shumeyko-partners-wb-unit-economics по WB-логистике v4.
Сначала прочитай AGENTS.md, docs/manifest.yml,
docs/specs/wb-logistics-cost-analysis-implementation.md и
docs/runbooks/wb-logistics-v4-continuation.md. Код, gate-fix и безопасная
staff-ссылка уже закоммичены и запушены в ветку
codex/incremental-source-refresh-rollout; HEAD/origin — 73b9894. На test
развернут runtime-73b9894-wb-logistics-v4-staff-link-20260717, production не
изменялся, клиентский feature flag выключен. Разрешенный immutable test-draft
имеет logistics gate ready и не опубликован как текущий; его локальный
идентификатор не хранится в Markdown. Accepted web/logistics specs уже
закрепляют отсутствие отдельного пункта «Логистика», сценарии «Сводка / Товары
/ Логистика / Возвраты / Расходы WB / Исходные данные», deep-link
#tables/logistics, answer-first состояния и mobile/accessibility criteria.
Синтетический target находится в
docs/design/wb-logistics-v4-analytics-target.html. Следующий шаг — визуально
принять target в реальном браузере до frontend-реализации. Также учти:
WB Finance не содержит причины покупательского возврата, но у WB есть отдельные
read-only источники goods-return и claims с разной семантикой и покрытием;
их подключение требует отдельного spec/probe и не должно придумывать причины.
Рабочее дерево грязное несвязанными retention/systemd и UI-изменениями — не
откатывай их и не включай в новый commit без ownership-аудита.
```

# Текущее состояние

- Расчетная методика: `wb-logistics-v4`.
- Формула ключа: `wb-order-product-v1`.
- Поддерживается только WB.
- Реализованы order/SKU-витрины, readiness-context, три read-only API,
  staff-only интерфейс, SQL-рекомендации и безопасный AI digest.
- Контексты v1-v3 и несовместимая версия ключа возвращают `needs_rebuild`.
- `SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=false` по умолчанию.
- `SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED=false` по умолчанию.
- Исправление реального снимка закоммичено как `8855752`, отправлено в
  `origin/codex/incremental-source-refresh-rollout` и развернуто только на test
  в release `runtime-8855752-wb-logistics-v4-gate-fix-20260717`. Production не
  затронут.
- Безопасная staff-навигация к конкретному разрешенному draft закоммичена как
  `73b9894`, запушена в ту же ветку и развернута на test в release
  `runtime-73b9894-wb-logistics-v4-staff-link-20260717`. Параметр `report_id`
  выбирается только из серверного списка отчетов, доступных текущей роли и
  tenant; произвольный draft не обходит authorization.
- На существующем полном test-снимке выполнен read-only preview после адаптации
  реальных схем и границ периода. Gate получил `ready`: source/order/SKU/report
  согласованы с допуском accepted spec, обязательных ошибок, конфликтов цепочек
  и dimension-расхождений нет; preview завершен rollback и не создал report
  run. Идентификатор снимка и клиентские агрегаты остаются в локальном
  операционном evidence, а не в Markdown.
- Создан новый immutable test-draft: logistics-context имеет `ready`, все
  контрольные суммы согласованы, report остается `draft` и не заменяет текущую
  публикацию. Идентификатор draft и клиентские объемы не фиксируются в Git или
  Markdown.
- Master-флаг включен на test только для consultant/admin, клиентский флаг
  остается `false`. Repository/API smoke вернул `ready` и подтвердил отсутствие
  raw/order identifiers в payload. Production и клиентский rollout не
  выполнены.
- Public health test-контура отдает build
  `20260717-tax-load-ux-v2-logistics-v4-gate-fix-v2`, schema v4 и
  `runtimeEnvironment=test`. Статус `degraded` связан с прежним безопасным
  source-refresh run `needs_configuration`, а не с логистическим расчетом.

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

Последний полный прогон ядра после gate-fix:

```text
731 passed, 5 warnings in 860.11s
```

Пять warnings — сторонние deprecation warnings FastAPI/TestClient и ChatKit;
они не блокируют текущий пакет.

Также успешно выполнены:

```bash
.venv/bin/ruff check .
node --check src/wb_unit_economics/web/static/app.js
.venv/bin/python scripts/generate_web_api_reference.py --check
.venv/bin/python scripts/validate_docs_manifest.py
.venv/bin/python scripts/validate_llm_docs.py
.venv/bin/python scripts/validate_specs.py docs/specs/wb-logistics-cost-analysis-implementation.md
.venv/bin/python scripts/validate_no_secrets.py
git diff --check
```

После staff-link изменения отдельно прошли два точечных API/UI-теста, Ruff,
`node --check`, spec validation, docs manifest, LLM links и
`git diff --cached --check`.

# Рабочее дерево

Основной пакет логистики v4, real-snapshot gate-fix и staff-link уже
закоммичены. Рабочее дерево по-прежнему содержит существовавшие ранее
несвязанные изменения. Не считать их частью нового UX/returns этапа и не
откатывать без отдельного запроса:

- изменения retention/source-refresh документации;
- `deploy/systemd/shumeiko-web-backup.service`;
- новые source-refresh retention service/timer;
- `scripts/run_source_refresh_retention_maintenance.py`;
- `tests/test_source_refresh_retention_maintenance.py`;
- другие пользовательские изменения web UI, если их происхождение не
  подтверждено diff-аудитом.

Перед commit/stage сначала отделить логистический diff от посторонних файлов.
Не использовать destructive Git-команды.

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

1. Открыть `docs/design/wb-logistics-v4-analytics-target.html` в реальном
   браузере и принять или скорректировать структуру на desktop 1440×900 и mobile
   390×844. Проверить первый приоритетный action, полный глобальный срез,
   горизонтальную nested navigation, focus outline и отсутствие overflow.
2. После визуальной приемки реализовать изолированно: единый sidebar entry,
   nested scenarios, `#tables/logistics`, overview-action, focus/Back/Forward и
   state matrix. Не смешивать эту работу с retention/report-wizard hunks.
3. Проверить desktop/mobile, keyboard/focus, deep-link к разрешенному draft,
   отсутствие logistics API-вызова и косвенного раскрытия draft для client role
   при выключенном client flag.
4. Выполнить visual regression относительно принятого target, точечные UI/API
   тесты, `node --check`, Ruff, spec/docs/no-secrets проверки и только затем
   готовить отдельный commit/dependent PR.
5. Отдельно подготовить spec/probe для read-only `goods-return` и `claims`:
   доступ токена, retention, coverage, join по `srid`/заказу и явные unmatched
   статусы. Не смешивать этот источник с уже готовым Finance gate.
6. До завершения UX-приемки использовать текущую staff-ссылку вида
   `/cabinet?client_id=<authorized_client>&report_id=<authorized_draft>#logistics`;
   конкретные идентификаторы брать из локального разрешенного операционного
   контекста. Для финансовых KPI выбирать границы полных недель внутри периода
   отчета; на неполных границах логистика точная, а недельные финансовые KPI
   намеренно `null`.
7. Клиентский флаг оставить выключенным; production и текущую публикацию не
   менять без отдельного согласования.

# Что не входит в текущий этап

- Excel-экспорт анализа логистики;
- габариты и контрольные замеры;
- маршруты и локализация складов;
- тарифный калькулятор;
- калькулятор маржинального дохода;
- клиентский rollout;
- любые write-операции во внешние системы.
