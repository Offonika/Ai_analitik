---
title: "Расписание source refresh WB/1C"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md"
updated_at: "2026-07-13"
---

# Назначение

> **Статус active.** Production timers, отдельный systemd worker, full/daily
> refresh и ручной incremental smoke проверены 13.07.2026. Два последовательных
> incremental run создали только staff-черновики, завершились за `9:18` и
> `8:45`, дали одинаковые `19 230` расчетных строк и одинаковые KPI; текущий
> опубликованный отчет не переключался. После включения drop-ins штатный
> production worker повторил тот же результат за `8:36`.

Этот runbook описывает безопасное расписание `source refresh` для web-кабинета
Shumeyko. Расписание запускает только read-only CLI
`scripts/run_source_refresh.py`; raw snapshots остаются в `data/source_refresh`
и не публикуются клиенту напрямую.

# Расписание

- Daily refresh: каждый час в `*:15 MSK`, режим `daily`.
- Weekly full refresh: понедельник в `08:15 MSK`, режим `full`.

`incremental` — ручной staff-режим между ними. Он повторно читает последние
`28` дней WB, свежую 1C за полный отчетный период, атомарно заменяет окно daily
facts и создает новый immutable draft без чтения всей raw-истории. Режим
включается только после shadow parity флагом
`SHUMEYKO_SOURCE_REFRESH_INCREMENTAL_ENABLED=true`. При отсутствии полной базы,
разрыве coverage или ошибке parity возвращается `needs_full_refresh`; полный
refresh автоматически не запускается.

Самостоятельный режим `onec-only` без `source_report_id` используется для
диагностики/перезагрузки 1С raw snapshots и не создаёт отчёт. Если явно передан
исходный отчёт, система создаёт только staff-черновик: переиспользует полный
неизменяемый WB-снимок с покрытием всего периода либо автоматически выполняет
`full` read-only refresh. Публикация и переключение текущего клиентского отчёта
в обоих случаях запрещены без отдельной приёмки.

На текущем сервере systemd работает в timezone `Europe/Moscow`, поэтому
`OnCalendar` в unit-файлах задан локальным московским временем. Если сервер
переезжает в другой timezone, перед установкой timers нужно либо вернуть
`Europe/Moscow`, либо заменить время на эквивалентное локальное.

# Файлы

Шаблоны лежат в:

```text
deploy/systemd/shumeiko-source-refresh-daily.service
deploy/systemd/shumeiko-source-refresh-daily.timer
deploy/systemd/shumeiko-source-refresh-weekly.service
deploy/systemd/shumeiko-source-refresh-weekly.timer
deploy/systemd/shumeiko-source-refresh-worker@.service
deploy/systemd/shumeiko-source-refresh-worker@.service.d/incremental-refresh.conf
deploy/systemd/shumeiko-source-refresh-worker@.service.d/marketplace-facts.conf
deploy/systemd/shumeiko-source-refresh-watchdog.service
deploy/systemd/shumeiko-source-refresh-watchdog.timer
deploy/systemd/shumeiko-web-prod.service.d/incremental-refresh.conf
```

Оба service-файла используют:

- `WorkingDirectory=/opt/shumeyko-runtime/prod/current`;
- проектный `.venv/bin/python`;
- `EnvironmentFile=/etc/shumeiko-web-prod.env`;
- `SHUMEYKO_SOURCE_REFRESH_TENANT=shumeyko` как безопасный tenant по умолчанию.

Ручной запуск из web, совместимая кнопка 1С, AI-команда, пересборка после
загрузки сопоставления и production daily/weekly выполняют отдельный шаблон
`shumeiko-source-refresh-worker@<run_id>.service`. Web-процесс только создаёт
`queued` run и запускает unit; чтение источников и сборка отчёта внутри
`shumeiko-web-prod.service` запрещены. Watchdog раз в минуту проверяет heartbeat.
Локальный `cli:<pid>:<run_id>` fallback разрешён только для SQLite/dev; stale
CLI run восстанавливается лишь после подтверждения отсутствия процесса.

Фоновый worker ограничен `MemoryHigh=3G`, `MemoryMax=4G` и
`MemorySwapMax=1G`. На production он включён в systemd-oomd как приоритетный
кандидат на завершение при давлении памяти. Поэтому тяжёлый refresh может
завершиться управляемой ошибкой и быть продолжен по checkpoint, но не должен
забирать память у SSH, PostgreSQL и базовых системных служб.

Секреты, токены и содержимое `.env` не переносить в unit-файлы. Для production
refresh доступы должны приходить из encrypted tenant integrations.

# Установка

```bash
sudo cp deploy/systemd/shumeiko-source-refresh-*.service /etc/systemd/system/
sudo cp deploy/systemd/shumeiko-source-refresh-*.timer /etc/systemd/system/
sudo install -d /etc/systemd/system/shumeiko-source-refresh-worker@.service.d
sudo install -d /etc/systemd/system/shumeiko-web-prod.service.d
sudo cp deploy/systemd/shumeiko-source-refresh-worker@.service.d/*.conf \
  /etc/systemd/system/shumeiko-source-refresh-worker@.service.d/
sudo cp deploy/systemd/shumeiko-web-prod.service.d/incremental-refresh.conf \
  /etc/systemd/system/shumeiko-web-prod.service.d/
sudo systemctl daemon-reload
sudo systemctl restart shumeiko-web-prod.service
sudo systemctl enable --now shumeiko-source-refresh-watchdog.timer
sudo systemctl enable --now shumeiko-source-refresh-daily.timer
sudo systemctl enable --now shumeiko-source-refresh-weekly.timer
```

Если tenant id отличается от `shumeyko`, переопределить переменную через drop-in:

```bash
sudo systemctl edit shumeiko-source-refresh-daily.service
sudo systemctl edit shumeiko-source-refresh-weekly.service
```

Drop-in:

```ini
[Service]
Environment=SHUMEYKO_SOURCE_REFRESH_TENANT=<tenant_id>
```

Версионированные drop-ins включают staff incremental только вместе с
daily-facts и DB-first. Rollback не требует изменения файла с секретами:

```bash
sudo rm /etc/systemd/system/shumeiko-web-prod.service.d/incremental-refresh.conf
sudo rm \
  /etc/systemd/system/shumeiko-source-refresh-worker@.service.d/incremental-refresh.conf
sudo systemctl daemon-reload
sudo systemctl restart shumeiko-web-prod.service
```

Перед rollback убедиться, что incremental worker не активен. Уже созданные
immutable draft/report snapshots не удалять этой командой.

# Проверка

Preflight без внешних WB/1C чтений и без создания `source_refresh_run`:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/check_source_refresh_preflight.py \
  --tenant shumeyko \
  --mode full
```

Preflight проверяет tenant, runtime-ready WB/1C integrations, mapping source,
guard свободного места для `source_refresh_root`, последний refresh того же
режима и флаг `SHUMEYKO_SOURCE_REFRESH_ENABLED`. Если команда пишет
`Health: blocked`, сначала устранить перечисленные blockers.

Если preflight показывает `source refresh low disk`, сначала запустить
read-only storage audit:

```bash
.venv/bin/python scripts/check_source_refresh_storage.py \
  --source-root data/source_refresh
```

Audit показывает текущий free-space guard, protected/reclaimable
`source_refresh` snapshots, крупнейшие локальные `data/` и `reports/` каталоги
и ничего не удаляет. Для удаления старых `source_refresh` snapshots использовать
только отдельный dry-run-first `scripts/prune_source_refresh.py`.

Dry-run без чтения внешних источников:

```bash
SHUMEYKO_DATABASE_URL=... .venv/bin/python scripts/run_source_refresh.py \
  --tenant shumeyko \
  --mode full \
  --dry-run
```

Проверка timers:

```bash
systemctl list-timers 'shumeiko-source-refresh-*'
journalctl -u shumeiko-source-refresh-daily.service -n 100 --no-pager
journalctl -u shumeiko-source-refresh-weekly.service -n 100 --no-pager
```

# Восстановление зависшего legacy refresh

Сначала остановить web-процесс, который владеет старой in-process задачей.
Затем выполнить dry-run ремонта и только после сверки применить его:

```bash
.venv/bin/python scripts/repair_source_refresh_run.py --run-id <run_id>
.venv/bin/python scripts/repair_source_refresh_run.py --run-id <run_id> --apply
```

Команда переводит только незавершённый run в `failed`; snapshots, manifests,
collections и аналитические очереди не удаляются. Повторный запуск создаётся
как новый run с `resume_mode=auto`.

Ожидаемый лог CLI содержит `Source refresh`, `Status`, `Mode`, `Snapshot set`
и `Period`. Логи не должны содержать токены, connection strings или raw payload.

После первого daily timer:

```bash
.venv/bin/python scripts/check_source_refresh_health.py \
  --tenant shumeyko \
  --mode daily \
  --max-age-hours 2 \
  --systemd
```

Коды выхода health helper:

- `0`: свежий успешный или требующий проверки run (`source_loaded`,
  `report_created`, `needs_review`, `dry_run_ready`);
- `1`: свежий run завершился `failed`, `needs_configuration`,
  `blocked_low_disk` или `blocked_active_refresh`;
- `2`: run не найден, устарел, еще выполняется или БД недоступна.

Helper печатает только `source_refresh_run_id`, статус, период, `snapshot_set_id`,
`newReportRunId`, active run, свободное место source root и статусы collections.
Raw paths, raw payload и секреты не выводятся.

`scripts/run_source_refresh.py` возвращает код `0` для управляемых статусов
без внешних чтений (`blocked_low_disk`, `blocked_active_refresh`,
`needs_configuration`) и для `needs_review`, чтобы systemd oneshot не переходил
в failed при штатном guard. Для мониторинга blocked/config/review statuses
использовать health helper выше.
Для неожиданных падений `errorMessage` содержит тип исключения и короткое
очищенное сообщение; длинные token/password/secret-подобные значения
маскируются.
Новый report run должен становиться current только в самом конце успешного
refresh. Если сборка артефактов прошла, но позже возникла ошибка, новый report
остается draft, а предыдущий published report остается рабочим.

Перед тяжелыми чтениями WB/Ozon scheduler проверяет 1С через read-only
`$metadata`. При `404`, сетевой ошибке или невалидном EDMX run завершается
`failed` до выгрузки WB/Ozon. В карточке интеграции ручная проверка и
автоматическая runtime-проверка показываются отдельно; более новый runtime-сбой
не должен скрываться старым `check_ok`.

После failed run сервис автоматически сохраняет только последние
`SHUMEYKO_SOURCE_REFRESH_FAILED_SNAPSHOT_KEEP` failed snapshots, default `2`.
Автоочистка не затрагивает successful/active runs, snapshots опубликованных
отчетов, symlinks и пути вне `source_refresh_root`. Штатный prune CLI ниже
остается отдельным способом общей retention-очистки.

Для безопасной очистки старых локальных raw snapshots сначала запускать dry-run:

```bash
.venv/bin/python scripts/prune_source_refresh.py \
  --source-root data/source_refresh \
  --daily-keep 3 \
  --full-keep 2 \
  --protect-snapshot-set <published_snapshot_set_id>
```

Удаление выполняется только при явном `--apply`. Скрипт не трогает `.env`,
`reports`, `data/web`, PostgreSQL и пути вне `source_refresh_root`.
Если скрипт не может прочитать PostgreSQL из-за peer-auth, перед `--apply`
передать все `source_snapshot_set_id` опубликованных отчетов через
`--protect-snapshot-set`.

На production общий filesystem retention запускается отдельным
`shumeiko-source-refresh-prune.timer` ежедневно в 03:45 с небольшим случайным
сдвигом. Он сохраняет три последних daily, два последних full, все snapshots из
published/draft lineage и явно защищённый WB parity snapshot
`daily-20260712-065846`. Service использует тот же fail-closed PostgreSQL
protection: ошибка чтения lineage завершает запуск без удаления файлов.

Для общей DB-first готовности публикации и интеграций:

```bash
.venv/bin/python scripts/check_db_first_publication.py \
  --require-postgres \
  --require-files
```

Если нужно считать отсутствие runtime-ready WB/1C integrations блокером:

```bash
.venv/bin/python scripts/check_db_first_publication.py \
  --require-postgres \
  --require-files \
  --require-integrations
```

# Поведение при ошибках

- Если интеграции не настроены или находятся в `hash_only`, запуск завершается
  статусом `needs_configuration`, новый отчет не публикуется.
- Если свободного места меньше guard-порога, запуск завершается
  `blocked_low_disk` до WB/1C API-вызовов и без аварийного exit code процесса.
- Если уже идет конфликтующий refresh, запуск завершается
  `blocked_active_refresh` и без аварийного exit code процесса.
- Если обязательный источник WB/1C/mapping падает, статус `failed`, предыдущий
  отчет остается текущим рабочим артефактом.
- Если опциональный источник падает, новый отчет может быть создан со статусом
  `needs_review`.
- Если параллельно уже идет refresh того же `tenant+mode`, или `daily` стартует
  во время активного `full`, создается blocked run; это штатная защита от дублей
  и конкуренции за диск/память.
- Завершенный daily run со статусом `source_loaded` не считается активным и не
  блокирует следующий запуск; active-защита учитывает только незавершенные runs.
- Production scheduler и health helper не читают локальный `.env`; runtime config
  приходит из systemd environment, а WB/1C доступы — из encrypted tenant
  integrations.
- В переходном `SHUMEYKO_SOURCE_REFRESH_RAW_DB_MODE=legacy` сохраняется прежняя
  запись небольших marketplace collections в `source_snapshot_rows`. После
  parity-check production переключается на `files_only`: immutable WB/Ozon JSON
  в `source_refresh_root` становится авторитетным raw snapshot, collection
  сохраняет row count/hash/path и `rowPersistence.status=file_authoritative`,
  а PostgreSQL получает дневные/типизированные facts без полного raw payload.
  1С и mapping пока используют прежние правила и лимит 25 MiB.
- Для Ozon дополнительно требуется
  `SHUMEYKO_SOURCE_REFRESH_OZON_FILES_ONLY_ENABLED=true`. До отдельной сверки
  Ozon этот флаг не включается: типизированные operations строятся в тени, а
  raw-строки продолжают сохраняться для совместимости работающего web-процесса.
- Интервал WB Finance задается
  `SHUMEYKO_SOURCE_REFRESH_WB_REQUEST_DELAY_SECONDS`, а отдельный интервал
  Content API для карточек —
  `SHUMEYKO_SOURCE_REFRESH_WB_CONTENT_REQUEST_DELAY_SECONDS`. Их нельзя
  объединять: у endpoint-ов разные лимиты запросов.
