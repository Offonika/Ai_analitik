---
spec_id: "source-refresh-database-retention"
title: "Source refresh: ретенция PostgreSQL и освобождение диска"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
related_code:
  - scripts/prune_source_refresh_database.py
  - scripts/prune_source_refresh.py
  - scripts/create_maintenance_backup.py
  - src/wb_unit_economics/maintenance_safety.py
  - src/wb_unit_economics/web/models.py
related_tests:
  - tests/test_source_refresh_database_retention.py
  - tests/test_maintenance_safety.py
depends_on:
  - docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md
supersedes: []
rollout_required: true
updated_at: "2026-07-12"
---

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

Не входит:

- автоматический `VACUUM FULL`, `CLUSTER` или переписывание таблицы;
- удаление опубликованных отчетов, расчетных витрин или audit events;
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

# Критерии приемки

- Dry-run не меняет количество строк.
- Published/draft lineage, active, recent и composite-base runs защищены.
- Прерванный apply можно безопасно повторить.
- Команда не печатает payload, токены или URL подключения.
- S3 backup создается потоково, фиксирует version id, полностью читается обратно
  для SHA-256 и `pg_restore --list`; повреждение, смена версии или отключенное
  versioning блокируют destructive preflight.
- После apply опубликованный отчет и текущий source refresh остаются читаемыми.
- Новый запуск не воссоздает `uq_source_snapshot_row_hash`.
- Проверки спецификаций, manifest и релевантные pytest проходят.

## Changelog

- 2026-07-12: bound repack free-space preflight to the PostgreSQL data
  filesystem and documented the 30 GiB / 1.5x minimum.
- 2026-07-12: added a fail-closed daily filesystem-retention timer while keeping
  the accepted WB parity snapshot explicitly protected.
- 2026-07-11: accepted S3 as an off-host maintenance-backup target with
  version-pinned streaming readback and no local full-size dump.
