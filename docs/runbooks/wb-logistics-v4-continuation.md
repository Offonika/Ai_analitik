---
title: "Продолжение работ по WB-логистике v4"
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

# Текст для нового чата

```text
Продолжи работу в /opt/shumeyko-partners-wb-unit-economics по staff-ready
блоку анализа логистики WB. Сначала прочитай AGENTS.md, docs/manifest.yml,
docs/specs/wb-logistics-cost-analysis-implementation.md и этот handoff.
Методика — wb-logistics-v4, ключ — wb-order-product-v1. Кодовая часть и
hardening реализованы, 720 тестов прошли. Feature flags выключены, deployment,
test-миграция, новый read-only снимок WB и staff-rollout не выполнялись.
Рабочее дерево уже было грязным: не откатывай и не включай в логистический
коммит несвязанные retention/systemd и другие пользовательские изменения.
Ближайший безопасный шаг — проверить diff и подготовить изолированный handoff
к test-rollout либо выполнить test-rollout только после явного разрешения.
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
- На существующем полном test-снимке `full-20260716-171834` выполнен read-only
  preview после адаптации реальных схем и границ периода. Gate получил
  `ready`: source/order/SKU/control равны `16 085 743,59 руб.`, обязательных
  ошибок, конфликтов цепочек и dimension-расхождений нет; preview завершен
  rollback и не создал report run.
- Создан новый immutable draft
  `shumeyko_logistics_v4_20260717_1340`: logistics-context имеет `ready`, все
  четыре контрольные суммы равны `16 085 743,59 руб.`, построено 85 225
  order-сегментов и 5 632 недельных SKU-строки. Report остается `draft` и не
  заменяет текущую публикацию.
- Master-флаг включен на test только для consultant/admin, клиентский флаг
  остается `false`. Repository/API smoke вернул `ready`, 714 товарных позиций,
  76 200 учитываемых заказов и отсутствие raw/order identifiers в payload.
  Production и клиентский rollout не выполнены.

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

Последний полный прогон после исправлений:

```text
720 passed, 5 warnings in 535.59s
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

# Рабочее дерево

Рабочее дерево содержит большой незакоммиченный пакет логистики v1-v4 и
существовавшие ранее несвязанные изменения. В частности, не считать частью
этого handoff и не откатывать без отдельного запроса:

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

1. Consultant/admin открыть draft `shumeyko_logistics_v4_20260717_1340` в
   разделе `Анализ логистики` и выполнить визуальную приемку нескольких
   обезличенных цепочек, рейтингов и пояснений.
2. Для финансовых KPI выбрать границы полных недель, например
   `06.04.2026–28.06.2026`; для полного квартала `01.04.2026–30.06.2026`
   логистика точная, а недельные выручка/прибыль намеренно `null` из-за двух
   неполных граничных недель.
3. Устранить только оставшиеся финансовые publication blockers основного
   отчета; логистический gate их не маскирует и уже имеет `ready`.
4. Клиентский флаг оставить выключенным до отдельного согласования.
8. Rollback скрывает раздел флагом, но не снимает publication blocker с
   report run, провалившего обязательный gate.

# Что не входит в текущий этап

- Excel-экспорт анализа логистики;
- габариты и контрольные замеры;
- маршруты и локализация складов;
- тарифный калькулятор;
- калькулятор маржинального дохода;
- клиентский rollout;
- любые write-операции во внешние системы.
