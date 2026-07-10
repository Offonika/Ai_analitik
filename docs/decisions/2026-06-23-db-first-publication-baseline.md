---
title: "DB-first publication baseline"
doc_type: decision
domain: "marketplace-analytics"
audience: ["engineering", "operations", "consultant"]
status: accepted
source_of_truth: false
snapshot_as_of: "2026-06-23"
updated_at: "2026-07-10"
source_spec: "docs/specs/wb-unit-economics-db-first-report-marts.md"
---

> **Исторический снимок на 23.06.2026.** Документ не определяет текущий
> опубликованный отчет. Живое состояние всегда читается из БД по явному
> `report_id`.

# Контекст

23.06.2026 рабочая web-витрина Шумейко WB/1C была опубликована через DB-first
контур: расчетные витрины сохранены в Postgres, а Excel/CSV/HTML/DOCX/PDF
созданы как артефакты из опубликованного `report_id`.

Этот документ фиксирует исторический эксплуатационный baseline и
parity-решение, чтобы не смешивать снимок на 23.06.2026 с живым отчетом.

# Baseline

- Tenant: `shumeyko`.
- Report snapshot: `excel_mvp_2026_03_01_2026_06_17`.
- Lineage: `db_first_report_marts`.
- Publication status: `published/current`.
- Schema version: `2026_06_23_db_first_report_marts`.
- Report period: `2026-03-01` — `2026-06-17`.
- `unitRows`: 18179.
- `lostSales`: 776.
- Artifact registry: 9 ready records: Excel, 5 CSV, HTML, DOCX, PDF.
- Stable Excel path: `reports/shumeyko_wb_excel_mvp.xlsx`.

# Parity Decision

Воспроизводимое состояние снимка на 23.06.2026:

- Postgres `report_unit_rows`: 18179 строк.
- DB-first CSV `unitRows.csv`: 18179 data rows.
- Stable Excel sheet `Юнит экономика`: 18179 data rows.
- Power BI mart того снимка `unit_economics.csv`: 18179 data rows.
- `lostSales` в DB/CSV/Excel: 776 data rows.

Число `18820` не было найдено в docs/specs/tests/scripts того снимка как
приемочный критерий и не воспроизводится текущими локальными DB-first
артефактами. До появления доказательного старого эталона считать `18820`
устаревшим ориентиром из рабочего плана, а не обязательным acceptance number.

Если позже появится workbook, snapshot или audit pack, который воспроизводит
`18820`, разбор выполнять отдельно: сначала найти класс отличающихся строк и
только потом менять расчет или source selection. Молча подгонять строки нельзя.

# Source Refresh State As Of 2026-06-23

Расписание systemd работает, но source refresh не готов к live-загрузке:

- latest source refresh status: `needs_configuration`;
- причина: для tenant `shumeyko` нет runtime-ready WB/1C integrations;
- таймеры и feature flags не заменяют настройку `tenant_integrations`;
- `daily` остается rolling/source refresh и не публикует клиентский report;
- клиентскую публикацию должен делать только `weekly` или `full` после
  validation/export.

# Operational Check

Для повторной проверки этого исторического снимка использовать явный id:

```bash
.venv/bin/python scripts/check_db_first_publication.py \
  --report-id excel_mvp_2026_03_01_2026_06_17 \
  --require-postgres \
  --require-files
```

После настройки WB/1C интеграций дополнительно использовать:

```bash
.venv/bin/python scripts/check_db_first_publication.py \
  --report-id excel_mvp_2026_03_01_2026_06_17 \
  --require-postgres \
  --require-files \
  --require-integrations
```

# Guardrails

- `.env`, raw snapshots, токены и клиентские выгрузки не читать и не переносить
  в документы.
- WB/1C integrations должны быть read-only.
- Legacy Excel import остается только recovery path.
