---
spec_id: "workspace-shumeyko-web-cabinet-runtime-contours"
title: "Web-кабинет: production и test контуры"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "operations"]
source_of_truth: true
truth_scope: runtime-contours
truth_priority: 100
related_code: [src/wb_unit_economics/web/settings.py, src/wb_unit_economics/web/app.py, scripts/prepare_test_database.py, scripts/build_runtime_release.py, scripts/promote_runtime_release.py, scripts/check_runtime_health.py]
related_tests: [tests/test_web_app.py]
depends_on: [docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md]
related_specs: [docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md]
rollout_required: true
updated_at: "2026-07-15"
---

# Goal

Разделить клиентский production и внутренний test без остановки действующего
кабинета и без совместного использования БД, сессий, writable-каталогов или
deployment pointer.

# Runtime Contract

| Контур | Адрес | Порт | База | Доступ |
| --- | --- | ---: | --- | --- |
| production | `analitika.offonika.ru` | 8097 | `shumeyko_web_cabinet` | client, consultant, admin |
| test | `shumeiko.offonika.ru` | 8098 | `shumeyko_web_cabinet_test` | только consultant, admin |
| legacy rollback | без публичного маршрута | 8096 | production | временно, не более 24 часов после cutover |

Оба контура могут использовать один PostgreSQL cluster, но database URL,
session cookie, environment file, report root и source-refresh root всегда
различаются. Test работает от отдельного непривилегированного system user без
Linux capabilities и постоянно показывает заметную маркировку окружения.
Если PostgreSQL использует отдельную test-роль, ее полный database URL
передается генератору environment-файлов только через одноразовую переменную
`SHUMEYKO_TEST_DATABASE_URL`. Генератор обязан проверить имя test БД и не
выводить URL или пароль в stdout/stderr.

# Configuration And API

- `runtime_environment`: `development`, `production` или `test`;
- `client_login_enabled=false` запрещает client-only login без раскрытия
  существования учетной записи;
- `external_integrations_enabled=false` является master-switch для внешних
  WB/1С проверок и недиагностических source refresh;
- `maintenance_message` содержит только безопасный текст до 500 символов;
- `/api/health` возвращает `runtimeEnvironment` и `maintenanceMessage`, но не
  раскрывает URL БД, секреты или файловые пути.

# Test Database Clone

Test создается из согласованной копии production БД только при отсутствии
активного source refresh и наличии проверенного внешнего backup. До запуска
test обязательно:

- удалить sessions и live-check cache;
- отключить client-only пользователей;
- очистить integration hashes, hints, ciphertext/config и перевести
  интеграции в `disabled`;
- удалить очереди refresh/report generation и завершить унаследованные active
  runs безопасной ошибкой `test_clone_reset`;
- удалить ссылки на production raw paths;
- скопировать только файлы current published reports в test report root.

Sanitization должна быть идемпотентной: повторный запуск сохраняет current
report/workbook artifacts, уже находящиеся внутри разрешенного test report
root, и не переводит их в `unavailable`.

40 GiB production source snapshots не копируются. Для ручной end-to-end
проверки test использует только отдельно сохраненные read-only интеграции,
собственный snapshot root и retention `daily=1`, `full=1`, `failed=1`.
Автоматические timers для test запрещены.

# Release And Promotion

Release строится только из точного Git commit и содержит manifest с commit,
archive hash, dependency freeze hash и content hash. Каталог release после
сборки immutable. Test и production имеют независимые атомарные symlinks
`current`; production получает ровно проверенный test artifact.

Миграции до окончания 24-часового окна rollback только additive и обратно
совместимы. Rollback меняет production symlink или временно возвращает nginx
на legacy 8096; клиентская БД не восстанавливается без отдельного решения об
откате данных.

# Acceptance Criteria

- оба local health endpoint отвечают `200`, правильным environment и build ID;
- отдельные systemd timers проверяют health production и test не реже раза в
  минуту и падают при несовпадении environment или backend/static build;
- client-only login отклоняется в test, staff login работает;
- test mutation не появляется в production database;
- test не читает production snapshots/backups и не имеет automatic timers;
- production health `ok`, refresh не активен, current report и Excel доступны;
- unauthenticated reports/exports остаются закрыты, `.env`, JSON и XLSX не
  раздаются статически;
- DNS и TLS нового домена готовы до передачи ссылки клиенту;
- nginx reload атомарен, legacy 8096 сохраняется 24 часа для rollback.

# Changelog

- 2026-07-15: accepted разделение production/test, DB clone sanitization,
  immutable promotion и zero-downtime cutover.
- 2026-07-15: зафиксирована безопасная передача URL отдельной PostgreSQL-роли
  test-контура без вывода секрета.
- 2026-07-15: повторная sanitization сохраняет уже безопасно скопированные
  current report artifacts внутри test root.
