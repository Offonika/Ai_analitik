---
spec_id: "source-refresh-database-retention"
title: "Source refresh: ретенция PostgreSQL и освобождение диска"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
truth_scope: source-retention
truth_priority: 100
related_code:
  - scripts/archive_source_refresh_snapshots.py
  - scripts/prune_source_refresh_database.py
  - scripts/prune_source_refresh.py
  - scripts/prune_report_drafts.py
  - scripts/prune_runtime_releases.py
  - scripts/create_maintenance_backup.py
  - scripts/run_source_refresh_retention_maintenance.py
  - scripts/restore_marketplace_raw_rows.py
  - scripts/build_runtime_release.py
  - scripts/promote_runtime_release.py
  - deploy/systemd/shumeiko-runtime-release-prune.service
  - deploy/systemd/shumeiko-runtime-release-prune.timer
  - src/wb_unit_economics/maintenance_safety.py
  - src/wb_unit_economics/snapshot_archive.py
  - src/wb_unit_economics/runtime_release_lock.py
  - src/wb_unit_economics/web/models.py
related_tests:
  - tests/test_snapshot_archive.py
  - tests/test_source_refresh_database_retention.py
  - tests/test_report_draft_retention.py
  - tests/test_runtime_release_retention.py
  - tests/test_maintenance_safety.py
  - tests/test_source_refresh_retention_maintenance.py
  - tests/test_restore_marketplace_raw_rows.py
ai_sections:
  status: "Implementation Status"
  goal: "Цель"
  boundaries: "Границы"
  protected_runs: "Защищенные запуски"
  deletion: "Удаление"
  report_drafts: "Retention черновиков отчетов"
  backup_rollout: "Бэкапы и rollout"
  automatic_maintenance: "Автоматическое обслуживание"
  acceptance: "Критерии приемки"
code_anchors:
  - path: scripts/prune_report_drafts.py
    symbols: ["def select_draft_candidates", "def _apply", "def _remove_artifacts"]
  - path: scripts/prune_source_refresh_database.py
    symbols: ["def select_protected_run_ids", "def _verify_collection_files"]
  - path: scripts/run_source_refresh_retention_maintenance.py
    symbols: ["def maintenance", "def prune_old_maintenance_bundles"]
test_anchors:
  - path: tests/test_report_draft_retention.py
    symbols: ["test_select_draft_candidates_keeps_latest_recent_and_protected", "test_remove_artifacts_rejects_symlink_path"]
  - path: tests/test_source_refresh_retention_maintenance.py
    symbols: ["test_dry_run_checks_report_drafts_before_raw_and_filesystem"]
depends_on:
  - docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md
supersedes: []
rollout_required: true
updated_at: "2026-07-20"
---

# Implementation Status

Статус остается `accepted`. Dry-run-first CLI, maintenance safety и связанные
тесты существуют, но destructive apply/repack и восстановление из off-host
backup намеренно не выполняются ради документационной проверки. До отдельного
операционного smoke spec не повышается до `implemented`.

# Цель

Остановить неконтролируемый рост `wb_unit_economics.source_snapshot_rows`,
сохранив воспроизводимость опубликованных и готовящихся отчетов. Ретенция
файловых snapshot-директорий и строк PostgreSQL должна применять одинаковые
правила защиты lineage, но удаление строк БД выполняется отдельной командой.

После перехода marketplace-источника в режим `file_authoritative` его
неизменяемые raw-файлы, manifest и hashes являются источником
воспроизводимости. Построчные копии WB/Ozon в PostgreSQL после проверенного
переключения не относятся к report lineage и могут удаляться отдельно от
защищенного файлового snapshot.

## File-authoritative marketplace retention

Для `wb_finance_detail` и Ozon source types разрешено удаление raw DB rows из
защищенного report run только при одновременном выполнении условий:

- run завершен и не активен;
- collection имеет `rowPersistence.status=file_authoritative`;
- `raw_path` находится внутри настроенного `source_refresh_root`;
- каталог, manifest и все перечисленные в manifest файлы существуют;
- фактический SHA-256 каждого файла совпадает с manifest;
- collection сохраняет `snapshot_hash`, `row_count` и ссылку на run/report.

Проверка выполняется единым raw-integrity verifier, общим для retention,
перестроения отчета и восстановления строк. Он дополнительно требует точного
совпадения manifest с collection payload, полного множества output-файлов,
суммы `row_count`, `snapshot_hash` collection и фактических SHA-256. Успешная
проверка сохраняется в additive payload `rawIntegrity` с status, manifest hash,
числом файлов/строк и временем проверки. Само наличие этого payload не заменяет
повторную проверку непосредственно перед удалением.

Если хотя бы одна проверка не проходит, строки не являются кандидатом. Записи
`source_refresh_runs`, `source_refresh_collections`, защищенные raw-каталоги и
готовые report marts не удаляются. 1С и mapping продолжают использовать общие
lineage-правила ниже.

Физическое уменьшение relation выполняется отдельно после логического удаления:
обычный `VACUUM (ANALYZE)` возвращает страницы PostgreSQL для повторного
использования, а online `pg_repack` допускается только после проверенного
off-host backup, при остановленных refresh writers и достаточном временном
месте. `VACUUM FULL` не является штатным путем.

Свободное временное место для `pg_repack` проверяется на файловой системе
фактического PostgreSQL data path, а не на `/data` или в каталоге raw snapshots.
Операция разрешена только при свободном месте не менее
`max(30 GiB, 1.5 x оценка живой таблицы вместе с индексами)`.

Любой DB retention с `--apply` и любой online repack используют единый backup
verifier. Он требует custom-format dump БД, dump ролей, SHA-256 обоих файлов,
подтвержденный `pg_restore --list`, время создания и внешнее хранилище. Для
filesystem это mount, отличный от PostgreSQL data path и `/data`. Для S3 это
приватный versioned bucket, отдельный пользователь с доступом только к этому
bucket, URI и version id обоих объектов. S3 verifier повторно читает именно
зафиксированные версии, пересчитывает SHA-256 и потоково передает database dump
в `pg_restore --list`; локальная полная копия для проверки не создается. Dry-run
retention не требует backup.

Ozon collection допускается к file-authoritative удалению только для явно
поддерживаемого typed source и при одновременных
`rawIntegrity.status=verified`, `typedParity.status=matched` и
`typedParity.diagnosticsParity.status=matched`. Diagnostics parity сравнивает
полный legacy/typed Ozon P&L и web diagnostics по stable business grain, а не
aggregate-only итог или первые preview-строки. Префикс
`ozon_` сам по себе не дает права удалять raw DB rows.

Для post-cutover files-only run дополнительно обязателен
`typedParity.qualificationRunId`, указывающий на предыдущий полный legacy parity
того же tenant/client/source. Текущий run сверяется с immutable raw files. Ни
preview-limit, ни отсутствие legacy rows сами по себе не могут дать `matched`.
Restore preflight обязан прочитать JSON/CSV/TSV/XLSX data files, исключить
create/info control responses и восстановить ровно collection row count.

# Границы

Входит:

- dry-run по умолчанию;
- пакетное удаление raw `row_payload` из `source_snapshot_rows`;
- сохранение `source_refresh_runs` и `source_refresh_collections` как
  операционного журнала;
- защита report lineage и составных запусков;
- удаление логически избыточного уникального ограничения после отдельной
  проверки и полного логического бэкапа;
- обычный `VACUUM (ANALYZE)` после большой очистки для повторного использования
  освобожденных страниц.
- отдельный ежедневный filesystem-retention timer для уже завершённых и не
  защищённых snapshot-каталогов.
- dry-run-first удаление старых неактуальных report drafts вместе с их
  расчетными витринами, зарегистрированными файловыми артефактами и
  `SourceLoad`-связями после проверенного off-host backup;

Не входит:

- автоматический `VACUUM FULL`, `CLUSTER` или переписывание таблицы;
- удаление опубликованных, `superseded` или текущих отчетов и audit events;
- перенос бэкапов на тот же физический диск под видом внешнего бэкапа;
- дедупликация или изменение raw payload конкретного сохраненного запуска.

# Защищенные запуски

Строки snapshot нельзя удалять для:

- незавершенных запусков;
- запусков, связанных через `SourceLoad` с report run в статусе публикации
  `draft` или `published`;
- запусков, чей `snapshot_set_id` указан у такого report run;
- запусков, напрямую создающих или обновляющих такой report run;
- последних трех materialized `daily` и последних двух materialized `full`
  запусков для каждой пары `(tenant_id, client_id)`;
- последнего materialized `full` запуска каждого клиента;
- рекурсивных `base_source_refresh_run_id` и `resumed_from_run_id` любого
  защищенного запуска;
- явно переданных оператором `--protect-run`;
- запусков моложе 24 часов независимо от статуса.

Materialized run — завершенный недеградационный запуск со статусом
`source_loaded`, `report_created` или `needs_review`, в котором реально есть
snapshot rows. Blocked/dry-run записи без raw строк не влияют на объем.

# Удаление

- Команда сначала строит список кандидатов и считает строки без чтения или
  печати raw payload.
- Без `--apply` никакие записи не меняются.
- С `--apply` строки удаляются небольшими транзакциями по одному run и
  ограниченному batch size.
- Ошибка останавливает обработку; уже подтвержденные batch-транзакции не
  откатываются и повторный запуск безопасно продолжает остаток.
- Записи `source_refresh_runs` и `source_refresh_collections` остаются для
  диагностики, lineage и аудита.
- После удаления обычный `VACUUM (ANALYZE)` делает место повторно используемым
  PostgreSQL, но не обязан уменьшать файл на файловой системе.

## Retention черновиков отчетов

Отдельная команда `scripts/prune_report_drafts.py` удаляет только
`publication_status=draft AND is_current=false`. Для каждой области
`tenant/client/report_kind/organization` она всегда сохраняет последние
`keep_latest` черновиков, default `1`, и все черновики моложе `grace_hours`,
default `24`. Текущие, опубликованные и `superseded` отчеты не являются
кандидатами независимо от возраста.

Черновик дополнительно защищен, если на него ссылаются AI thread/client draft,
accounting workflow task/revision/delivery, data refresh как на исходный отчет
или immutable logistics analysis.
При `--apply` наличие активного source refresh блокирует всю операцию. Ссылки
завершенных `source_refresh_runs` и `data_refresh_jobs.new_report_run_id` на
удаляемый технический draft обнуляются, но сами операционные журналы
сохраняются.

Dry-run печатает только количество кандидатов, зависимых строк и суммарный
размер зарегистрированных артефактов. `--apply` требует тот же свежий
проверенный off-host backup, что и DB retention, повторно строит candidate set
в транзакции и удаляет все зависимые report marts атомарно. Файлы удаляются
только по зарегистрированным уникальным путям внутри настроенного
`reports_root`; общий, внешний, отсутствующий или symlink-путь не удаляется и
блокирует destructive preflight. Ошибка удаления файла после commit оставляет
только безопасный orphan и завершает команду ошибкой для ручной сверки.

# Индексы

`uq_source_snapshot_row_position` на
`(refresh_run_id, collection_id, row_number)` уже запрещает две строки в одной
позиции. Ограничение `uq_source_snapshot_row_hash` на тех же трех колонках плюс
`raw_payload_hash` логически слабее и не дает дополнительной защиты. Его можно
удалить после проверки наличия более строгого ограничения и отсутствия
активного refresh. Откат — повторное создание unique index/constraint, если
это потребуется по результатам мониторинга.

# Бэкапы и rollout

До первого `--apply` обязателен свежий custom-format логический бэкап рабочей
БД и dump ролей с проверкой структуры архивов и контрольных сумм. Локальная
копия на том же сервере является только страховкой операции; долговременная
копия должна находиться на другом диске или в объектном хранилище.

Порядок rollout:

1. Сделать и проверить логический бэкап.
2. Выполнить dry-run и сохранить только агрегированные количества.
3. Остановить новые refresh-запуски на время первой большой очистки.
4. Удалить избыточное ограничение, если preflight подтвержден.
5. Удалять кандидатов пакетами, контролируя свободное место и WAL.
6. Выполнить `VACUUM (ANALYZE)` и вернуть расписание.
7. Проверить PostgreSQL, web health и следующий dry-run refresh.

# Автоматическое обслуживание

Еженедельный `shumeiko-source-refresh-retention-maintenance.timer` запускает
fail-closed обертку после общей серверной уборки. Она:

1. использует настроенный versioned S3 bucket как основной off-host backup;
2. временно останавливает только активные refresh timers и блокирует запуск при
   наличии работающего worker;
3. потоково создает custom-format maintenance backup в S3, повторно читает
   зафиксированную version id и проверяет SHA-256 и `pg_restore --list` без
   локальной полноразмерной копии;
4. передает verification JSON в report-draft и raw-row DB retention `--apply`;
5. выполняет обычный `VACUUM (ANALYZE)` report/raw таблиц и filesystem
   retention;
6. удаляет старые локальные maintenance bundles после успешной S3-проверки и
   восстанавливает только те timers, которые были активны до обслуживания;
7. удаляет старые неактивные runtime releases под общим lock с builder и
   promoter, сохраняя active targets, последний rollback и 24-часовой grace.

Scheduled maintenance по умолчанию обрабатывает все tenant-контуры. Опциональный
`--tenant` остается только для адресного ручного запуска; пустой filter не
смешивает данные между tenant, а применяет retention независимо внутри каждой
области `tenant/client/report_kind/organization`.

Отдельный ежедневный snapshot archive переносит не моложе 48 часов по одному
каталогу в versioned S3. Каждый regular file загружается под immutable prefix,
фиксируются object `VersionId`, размер и SHA-256. До локального eviction каждый
объект полностью скачивается во временный файл и повторно хешируется; symlink,
special file, отключенное versioning, неполный readback или активный refresh
блокируют удаление. Локальный receipt с mode `0600` хранит точные версии всех
объектов. Restore скачивает их во временный каталог, проверяет размер и SHA-256
каждого файла и только затем атомарно возвращает исходное имя snapshot.

Filesystem backup остается ручным fallback: при запуске без `--s3-config`
обертка проверяет минимум 8 GiB свободного места и сохраняет последний локальный
maintenance bundle.

Runtime release cleanup по умолчанию является dry-run и использует общий
неблокирующий lock `/run/lock/shumeiko-runtime-release.lock` вместе с release
builder и promoter. Неожиданный path, symlink, невалидный manifest, active
target вне release root или занятый lock блокирует удаление. Apply сохраняет
обе active цели, минимум один полный rollback release и каталоги моложе grace;
старые незавершенные `.runtime-*` и неактивные legacy releases с
`sourceDirty=true` удаляются только после тех же проверок и не могут считаться
rollback.

Отдельный ежедневный `shumeiko-runtime-release-prune.timer` применяет только
fail-closed filesystem retention релизов: сохраняет обе active цели, два
последних полноценных rollback-релиза и 24-часовой grace. Тяжелый контур с S3
backup, DB retention и `VACUUM (ANALYZE)` остается еженедельным. Filesystem
snapshot prune запускается каждый час после rolling refresh и использует
DB-lineage protection, поэтому активные и опубликованные наборы не удаляются.
Production web и scheduled refresh units задают storage floor 20 GiB: новый
refresh завершается контролируемым `blocked_low_disk` до внешних чтений, если
свободное место `/data` опустилось ниже этого порога.

Любая ошибка backup, worker preflight, PostgreSQL или файловой защиты завершает
контур без продолжения к следующим destructive-шагам. Ежедневный operational
SQL-backup хранится локально одни сутки; off-host S3 maintenance backup создается
отдельно непосредственно перед weekly retention.

# Критерии приемки

- Dry-run не меняет количество строк.
- Published/draft lineage, active, recent и composite-base runs защищены.
- Прерванный apply можно безопасно повторить.
- Команда не печатает payload, токены или URL подключения.
- S3 backup создается потоково, фиксирует version id, полностью читается обратно
  для SHA-256 и `pg_restore --list`; повреждение, смена версии или отключенное
  versioning блокируют destructive preflight.
- После apply опубликованный отчет и текущий source refresh остаются читаемыми.
- Report-draft dry-run ничего не меняет; apply сохраняет текущие,
  published/superseded, свежие, последние и связанные с workflow/AI отчеты.
- Report artifacts удаляются только по уникальным regular-file путям внутри
  `reports_root`; небезопасный путь блокирует apply до изменения БД.
- Runtime cleanup не удаляет prod/test active targets, последний полный
  rollback или свежий release и не пересекается с build/promotion.
- Новый запуск не воссоздает `uq_source_snapshot_row_hash`.
- Проверки спецификаций, manifest и релевантные pytest проходят.

## Changelog

- 2026-07-20: добавлены versioned S3 archive/readback/restore receipts и
  ежедневный fail-closed eviction одного snapshot старше 48 часов.

- 2026-07-20: scheduled maintenance переведен с hardcoded tenant `shumeyko` на
  all-tenant retention; защита и `keep_latest` продолжают считаться отдельно
  внутри каждого tenant scope.

- 2026-07-20: filesystem snapshot prune переведен на hourly cadence, добавлен
  отдельный ежедневный fail-closed runtime release retention и обязательные
  mount dependencies для `/data`.

- 2026-07-20: added Ozon files-only qualification lineage, full-snapshot parity
  and multi-format restore requirements before raw DB deletion.
- 2026-07-18: enabled runtime release retention after introducing one shared
  fail-closed lock across build, promotion and cleanup, with active, rollback,
  grace, manifest and path guards.
- 2026-07-18: accepted automatic dry-run-first retention of stale non-current
  report drafts with off-host backup, workflow/AI guards, exact artifact paths,
  atomic mart deletion and weekly maintenance integration.
- 2026-07-16: добавлен еженедельный fail-closed maintenance timer с проверяемым
  backup, DB/filesystem retention и VACUUM ANALYZE; operational SQL-backup
  сокращен до одного дня. Weekly backup переключен на versioned TWC S3 без
  локальной полноразмерной копии. Release cleanup исключен до общего
  deployment-lock.
- 2026-07-12: bound repack free-space preflight to the PostgreSQL data
  filesystem and documented the 30 GiB / 1.5x minimum.
- 2026-07-12: added a fail-closed daily filesystem-retention timer while keeping
  the accepted WB parity snapshot explicitly protected.
- 2026-07-11: accepted S3 as an off-host maintenance-backup target with
  version-pinned streaming readback and no local full-size dump.
