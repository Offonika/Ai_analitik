---
title: "Scalable source refresh pipeline for 20 clients"
doc_type: decision
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: accepted
source_of_truth: true
truth_scope: source-refresh
truth_priority: 90
updated_at: "2026-08-04"
---

# Context

Один production full-run подтвердил, что внешние чтения WB/1С занимают минуты,
а основная длительность и память приходятся на повторные полные копии фактов,
расчётных payload и обычную запись Excel. Один монолитный worker связывает
получение источников, materialization, расчёт и все экспорты: ошибка последнего
этапа вынуждает повторять уже завершённую работу. Per-client lock предотвращает
дубли одного клиента, но не управляет общей нагрузкой нескольких клиентов.

Система должна обслуживать до 20 клиентов на текущем сервере 8 vCPU / 11 ГБ
RAM, оставляя PostgreSQL и web отзывчивыми. Вторничные staff drafts должны быть
готовы между `06:15` и `09:00`, но автоматическая публикация запрещена.

# Decision

## Orchestration and data boundaries

- `source_refresh_runs` остаётся orchestration root и lineage identity.
- Дочерние `source_refresh_tasks` разделяют run на `collect_sources`,
  `materialize_facts`, `build_report`, `export_excel` и `export_optional`.
- Task claim выполняется в PostgreSQL через `FOR UPDATE SKIP LOCKED`; зависимости
  и idempotency key не позволяют повторно выполнять succeeded-стадии.
- Временные transport/API ошибки получают не более двух повторов с backoff.
  Ошибки авторизации, mapping и `partial_source` считаются permanent.
- PostgreSQL хранит нормализованные facts и расчётные marts. Неизменяемые raw
  WB/1С остаются в файловом/S3-архиве и не возвращаются в web API.
- Web только создаёт run/export job и читает сохранённые summary/строки/artifact;
  расчёт и экспорт внутри HTTP-запроса запрещены.

## Resource model

- Facts записываются пакетами по 5 000 строк с потоковым digest; исходные
  объекты освобождаются до расчёта marts и экспорта.
- Большой лист Excel читается из PostgreSQL keyset-порциями по 1 000 строк и
  пишется в `write_only` workbook. Временный файл проверяется как ZIP/openpyxl
  и только затем атомарно переименовывается.
- Автоматический refresh формирует только Excel; DOCX/HTML/CSV создаются
  отдельной `export_optional` задачей по запросу.
- Один heavy worker ограничен `MemoryHigh=1.5G`, `MemoryMax=2G`. Общий
  `source-refresh.slice` ограничен `MemoryMax=5G`, `CPUQuota=500%`.
- Первый rollout использует один heavy slot. Два heavy включаются только после
  performance-canary; допустимы два heavy либо один heavy и два collector.

## Scheduling

- Scheduler запускается каждые пять минут и только создаёт idempotent queued
  runs для enabled client schedule.
- По вторникам в `06:15` client timezone создаётся incremental за последние
  28 дней WB с актуальной 1С и пересчётом только затронутых недель/месяцев.
- Monthly full распределён по воскресным ночным слотам: не более пяти клиентов
  в неделю; пятая неделя служит для retry/незавершённых запусков.
- Контрольный production full 11.08.2026 остаётся запуском исправленного
  heartbeat. Новое расписание не включается до test queue canary.

## Publication, retention and recovery

- Успешный build создаёт только staff draft. `published/current` меняется
  исключительно через существующую финансовую приёмку.
- Current, draft и published последних 12 месяцев остаются в PostgreSQL.
  Старый `superseded` сначала сериализуется в версионированный archive bundle
  с hash, methodology, lineage и S3 VersionId. Удаление marts допустимо только
  после verified readback и успешного restore-smoke.
- Restore возвращает архив как read-only report и не переключает `current`.
- Raw snapshots получают S3 lifecycle на три года; manifests, hashes, audit и
  готовые report artifacts сохраняются дольше.
- Rollback переключает runtime на предыдущий immutable release; additive
  таблицы и созданные drafts не удаляются.

# Consequences

Падение Excel больше не повторяет WB/1С и не теряет готовые marts. Очередь
ограничивает общую память, позволяет прогнозировать завершение и безопасно
масштабирует клиентов. Цена решения — дополнительные additive таблицы,
dispatcher/scheduler и необходимость поэтапного rollout с frozen-source parity,
performance и restore acceptance.

# Acceptance thresholds

- marts + Excel: не более 8 минут P95 на текущем объёме;
- peak одного heavy worker: не более 1,5 ГБ, двух — не более 3 ГБ;
- 20 запусков, созданных во вторник в `06:15`, завершают Excel до `09:00`;
- при двух workers health остаётся `200`, API P95 не более 500 мс, swap не
  используется web/PostgreSQL;
- incremental и full дают одинаковый результат до копейки на одинаковых
  frozen sources;
- остановка worker на любой стадии не меняет `published/current` и не
  повреждает succeeded-стадии.
