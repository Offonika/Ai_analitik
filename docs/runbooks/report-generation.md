---
title: "Сборка и проверка DB-first отчета"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: draft
updated_at: "2026-06-24"
source_spec: "docs/specs/wb-unit-economics-db-first-report-marts.md"
---

# Назначение

Этот runbook описывает безопасную DB-first сборку юнит-экономики Wildberries из
локальных snapshots или Postgres inputs. Он не описывает получение секретов и не
требует чтения `.env` вручную.

Штатный источник готового отчета:

```text
published/current report marts в БД
```

Excel, DOCX/PDF, HTML и CSV являются экспортами из опубликованного `report_id`.

Стабильный файл приемки:

```text
reports/shumeyko_wb_excel_mvp.xlsx
```

Если нужен архивный файл, указывать отдельный `--output`. По умолчанию сборка
перезаписывает стабильный файл.

# Перед запуском

Проверить:

- WB snapshots уже лежат в `data/wb_finance/`;
- карточки WB, если нужны для маппинга, лежат в `data/wb_product_cards/`;
- 1С samples лежат в `data/onec_samples/`;
- расширенный sample регистра продаж, если доступен, лежит в
  `data/onec_gross_profit_samples/`;
- выгрузка `Сопоставление товаров` из 1С, если доступна, лежит в
  `data/onec_marketplace_mapping/`.

Все эти папки локальные. Их содержимое не переносить в Git, Markdown, чат или
письма.

# Базовая DB-first сборка

Собрать расчетные витрины в БД, экспортировать артефакты и атомарно
опубликовать report:

```bash
.venv/bin/python scripts/rebuild_report_from_sources.py \
  --tenant-id shumeyko \
  --report-id excel_mvp_2026_03_01_2026_06_17 \
  --export-all
```

Экспортировать артефакты из уже сохраненного report:

```bash
.venv/bin/python scripts/export_report_artifacts.py \
  --report-id excel_mvp_2026_03_01_2026_06_17 \
  --excel --docx --pdf --html --csv
```

# Проверка опубликованной витрины

После публикации проверить, что БД, Excel и CSV смотрят на один и тот же
DB-first baseline:

```bash
.venv/bin/python scripts/check_db_first_publication.py \
  --require-postgres \
  --require-files
```

Ожидаемое состояние текущего опубликованного baseline:

- current report: `excel_mvp_2026_03_01_2026_06_17`;
- lineage: `db_first_report_marts`;
- `unitRows`: 18179;
- `lostSales`: 776;
- artifact registry: 9 ready records.

Если всплывает старый ориентир `18820` строк, не считать это автоматическим
регрессом. Текущий DB-first baseline зафиксирован в
`docs/decisions/2026-06-23-db-first-publication-baseline.md`: Postgres, Excel,
CSV и текущий Power BI mart сходятся на 18179 data rows. Число `18820` нужно
разбирать только при наличии старого воспроизводимого эталона.

# Legacy Excel сборка

Собрать Excel MVP из последних локальных snapshots:

```bash
.venv/bin/python scripts/build_excel_mvp_from_snapshots.py
```

Этот путь нужен для ручной сверки и rollback, но не является штатным источником
web-данных.

# Регулярное обновление источников

Для штатного обновления raw lineage WB/1С/mapping использовать source refresh:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/run_source_refresh.py \
  --tenant shumeyko \
  --mode full
```

`daily` режим читает rolling window и не публикует клиентский report, чтобы не
создать обрезанный отчет. Для публикации нового `report_run` использовать
`weekly` или `full`. В DB-first режиме включить:

```text
SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true
```

Если tenant integrations хранятся в `hash_only`, сначала настроить
`SHUMEYKO_INTEGRATION_SECRET_KEY` и пересохранить доступы в кабинете.
До появления runtime-ready интеграций `scripts/check_db_first_publication.py`
будет показывать warning по source refresh readiness, а
`scripts/check_source_refresh_health.py` будет видеть `needs_configuration`.
Это blocker настройки доступов, а не ошибка DB-first публикации.

После настройки WB/1C integrations проверить:

```bash
.venv/bin/python scripts/check_db_first_publication.py \
  --require-postgres \
  --require-files \
  --require-integrations
```

Период отчета задается параметрами сборки или опубликованным `report_run`.
Manifest WB/1С snapshots подтверждает только покрытие источников
(`source_coverage`). Если покрытие источников не закрывает выбранный
`report_period`, отчет должен показывать `partial_period`, `partial_source` или
`needs_review`, а не подставлять нули за недостающие даты.

Текущий опубликованный baseline: `01.03.2026 - 17.06.2026`. В этой ревизии
период формулируется как `март, апрель, май, июнь; июнь неполный, по
17.06.2026`.

Если weekly WB report list уже загружен, его нужно передавать явно, чтобы в
витрине появились подтвержденные показатели СПП:

```bash
.venv/bin/python scripts/build_excel_mvp_from_snapshots.py \
  --wb-report-list-dir data/wb_sales_report_list/<timestamp>
```

Если нужно явно указать 1С sample:

```bash
.venv/bin/python scripts/build_excel_mvp_from_snapshots.py \
  --onec-dir data/onec_samples/<timestamp>
```

Если нужно явно указать sample регистра продаж:

```bash
.venv/bin/python scripts/build_excel_mvp_from_snapshots.py \
  --onec-dir data/onec_samples/<timestamp> \
  --sales-register-dir data/onec_gross_profit_samples/<timestamp> \
  --sales-cost-amount-field Себестоимость
```

`СебестоимостьБезНДС` использовать только для сверочного запуска, если это
прямо требуется. Основной расчет текущего MVP использует `Себестоимость`.

# Сборка через локальный Postgres

Загрузить WB Finance snapshot:

```bash
.venv/bin/python scripts/load_wb_finance_postgres.py \
  --db-name shumeyko_wb_unit_economics \
  --port 55433 \
  --wb-finance-dir data/wb_finance/<timestamp> \
  --onec-dir data/onec_samples/<timestamp>
```

Загрузить расчетные входы:

```bash
.venv/bin/python scripts/load_calculation_inputs_postgres.py \
  --postgres-db-name shumeyko_wb_unit_economics \
  --postgres-port 55433 \
  --wb-finance-dir data/wb_finance/<timestamp> \
  --wb-cards-dir data/wb_product_cards/<timestamp> \
  --onec-dir data/onec_samples/<timestamp> \
  --onec-marketplace-mapping-dir data/onec_marketplace_mapping \
  --sales-register-dir data/onec_gross_profit_samples/<timestamp> \
  --sales-cost-amount-field Себестоимость \
  --snapshot-id <timestamp> \
  --replace-snapshot
```

Собрать отчет из Postgres-слоя:

```bash
.venv/bin/python scripts/build_excel_mvp_from_snapshots.py \
  --wb-finance-source postgres \
  --mapping-source postgres \
  --cost-source postgres \
  --postgres-db-name shumeyko_wb_unit_economics \
  --postgres-port 55433 \
  --postgres-snapshot-id <wb-finance-snapshot-id> \
  --mapping-snapshot-id <calculation-inputs-snapshot-id> \
  --cost-snapshot-id <calculation-inputs-snapshot-id>
```

# Проверка после сборки

Минимум перед передачей результата:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python scripts/validate_no_secrets.py
.venv/bin/python scripts/validate_docs_manifest.py
.venv/bin/python scripts/validate_llm_docs.py
```

Если менялись только клиентские тексты, достаточно проверок документации и
секретов. Если менялись расчет, Excel builder или коннекторы, запускать тесты.

# Экспорт для Power BI / Power Query

После сборки стабильного Excel можно выгрузить плоские клиентские витрины:

```bash
.venv/bin/python scripts/export_power_bi_marts.py
```

Скрипт читает только `reports/shumeyko_wb_excel_mvp.xlsx` и пишет CSV в
`reports/power_bi_marts/`. Эти файлы можно подключить через Power Query как
промежуточный вариант или использовать как контракт для Power BI. Power BI
подключается к расчетным витринам, а не к raw snapshots.

# Что проверить глазами

- `Дашборд` виден первым и показывает период, статус, дату расчета и версию
  методики.
- Основной клиентский лист `Юнит экономика` содержит русские бизнес-колонки и
  не показывает технические ключи вместо названий.
- `Динамика`, `Расходы WB`, `Возвраты`, `Упущенные продажи`,
  `Сверка с 1С ОПиУ`, `Ошибки данных` и `Методика` видны клиенту.
- `Дашборд` и `Сверка с 1С ОПиУ` показывают `Выручку до СПП`, `СПП`,
  `% СПП`, `Выручку после СПП` и статус источника СПП.
- В основной помесячной сверке `Сверка с 1С ОПиУ` себестоимость сравнивается
  с `Валовая прибыль 1С` по дате документа; ОПиУ остается справочным
  управленческим блоком и источником сверки расходов МП.
- Товарный результат называется `Маржинальный доход WB после налогов` или
  `Прибыль по юнит-экономике WB после налогов`, а не полной чистой прибылью
  бизнеса.
- Технические сверочные листы скрыты по умолчанию, но сохранены в workbook.
- `partial_source`, `missing_mapping`, `missing_cost`, `ambiguous_mapping` и
  `needs_review` не скрыты.
- `Хранение` и `WB Продвижение` сходятся с недельными контрольными суммами WB.
- Workbook не содержит `.env`, API keys, токены, webhook URL или raw secrets.

# Как формулировать статус

- `Готово к отправке`: проверки пройдены, ограничения нормальные для MVP.
- `Готово с ограничениями`: отчет можно смотреть, но нужно явно перечислить
  неполные источники или строки на сверку.
- `Блокер`: отчет нельзя передавать как приемочный; указать конкретную причину
  и следующий шаг.
