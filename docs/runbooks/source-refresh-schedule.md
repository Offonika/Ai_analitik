---
title: "Расписание source refresh WB/1C"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: draft
source_spec: "docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md"
updated_at: "2026-06-24"
---

# Назначение

Этот runbook описывает безопасное расписание `source refresh` для web-кабинета
Shumeyko. Расписание запускает только read-only CLI
`scripts/run_source_refresh.py`; raw snapshots остаются в `data/source_refresh`
и не публикуются клиенту напрямую.

# Расписание

- Daily refresh: каждый час в `*:15 MSK`, режим `daily`.
- Weekly full refresh: понедельник в `08:15 MSK`, режим `full`.

Режим `onec-only` использовать только для диагностики/перезагрузки 1С raw
snapshots. Он не должен публиковать клиентский `report_run`: клиентская витрина
создается только из `weekly`/`full` или ручного DB-first rebuild, где явно
переданы и WB, и 1С snapshots.

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
```

Оба service-файла используют:

- `WorkingDirectory=/opt/shumeyko-partners-wb-unit-economics`;
- проектный `.venv/bin/python`;
- `EnvironmentFile=/etc/shumeiko-web.env`;
- `SHUMEYKO_SOURCE_REFRESH_TENANT=shumeyko` как безопасный tenant по умолчанию.

Секреты, токены и содержимое `.env` не переносить в unit-файлы. Для production
refresh доступы должны приходить из encrypted tenant integrations.

# Установка

```bash
sudo cp deploy/systemd/shumeiko-source-refresh-*.service /etc/systemd/system/
sudo cp deploy/systemd/shumeiko-source-refresh-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
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
- Для загруженных WB/1C/mapping collections raw rows пишутся в
  `source_snapshot_rows`. Эти строки нужны для воспроизводимости и не
  публикуются в клиентский UI.
