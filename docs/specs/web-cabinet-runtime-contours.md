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
related_code:
  - src/wb_unit_economics/web/settings.py
  - src/wb_unit_economics/web/app.py
  - src/wb_unit_economics/runtime_release_lock.py
  - scripts/prepare_test_database.py
  - scripts/build_runtime_release.py
  - scripts/promote_runtime_release.py
  - scripts/prune_runtime_releases.py
  - scripts/check_runtime_health.py
  - scripts/check_runtime_contour_drift.py
  - scripts/check_web_cabinet_health.py
  - deploy/systemd/shumeiko-web-prod.service
  - deploy/systemd/shumeiko-web-test.service
  - deploy/systemd/shumeiko-web-test.service.d/zzzz-unit-economics-calculator-staff-test.conf
  - deploy/systemd/shumeiko-web-prod-health.service
  - deploy/systemd/shumeiko-web-test-health.service
  - deploy/systemd/shumeiko-web-prod.service.d/corporate-proxy-login-shell.conf
  - deploy/nginx/analitika.offonika.ru.conf
  - deploy/nginx/shumeiko.offonika.ru.conf
related_tests: [tests/test_web_app.py, tests/test_runtime_contour_scripts.py, tests/test_runtime_contour_drift.py, tests/test_runtime_release_retention.py]
depends_on: [docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md]
related_specs: [docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md]
rollout_required: true
updated_at: "2026-07-24"
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

Legacy process на 8096 завершил 24-часовое окно cutover и больше не входит в
deployment contract. Его unit, EnvironmentFile и nginx route должны
отсутствовать. Rollback выполняется только переключением production symlink на
предыдущий проверенный immutable release.

Оба контура могут использовать один PostgreSQL cluster, но database URL,
session cookie, environment file, report root и source-refresh root всегда
различаются. Test работает от отдельного непривилегированного system user без
Linux capabilities и постоянно показывает заметную маркировку окружения.
Production report root находится в `/data/shumeyko/prod/reports`, test — в
`/data/shumeyko/test/reports`; writable runtime artifacts не размещаются внутри
Git checkout.
Обязательные non-secret границы (`runtime_environment`, cookie name, client
login, external integrations и writable roots) повторяются в versioned
systemd unit и имеют приоритет над EnvironmentFile. Секреты и database URL
остаются только в EnvironmentFile.
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
- в `test` при выключенном master-switch статусы `needs_configuration` и
  `needs_full_refresh` остаются видимыми в source-refresh полях, но не понижают
  общий health; реальные `failed`, `blocked_low_disk` и другие аварии по-прежнему
  возвращают `degraded`;
- `maintenance_message` содержит только безопасный текст до 500 символов;
- `/api/health` возвращает `runtimeEnvironment` и `maintenanceMessage`, но не
  раскрывает URL БД, секреты или файловые пути.
- Если production AI использует одобренный корпоративный proxy из root login
  profile, production unit должен подключать versioned drop-in
  `deploy/systemd/shumeiko-web-prod.service.d/corporate-proxy-login-shell.conf`.
  Он загружает профиль только при запуске uvicorn и не копирует URL или
  credentials proxy в Git либо runtime EnvironmentFile.

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

Build, promotion и release retention используют один неблокирующий exclusive
lock `/run/lock/shumeiko-runtime-release.lock`. Занятый lock завершает любую из
трех операций без изменений. Retention по умолчанию работает как dry-run,
всегда защищает цели `prod/current` и `test/current`, последний неактивный
полный release для rollback и все каталоги моложе 24 часов. `--apply` доступен
только root; symlink, посторонний entry, невалидный manifest или active target
за пределами release root блокирует всю операцию. Старые `.runtime-*` staging
каталоги и неактивные legacy releases с `sourceDirty=true` можно удалять только
по тем же правилам и под тем же lock; dirty release не считается rollback.

Скопированный runtime `.venv` обязан импортировать пакет только из `src` того
же immutable release. Editable-ссылка на рабочий репозиторий или другой внешний
checkout запрещена; bootstrap выбора `release/src` входит отдельным hash в
manifest и в общий content hash.

Миграции в пределах rollback window только additive и обратно совместимы.
Rollback меняет production symlink на предыдущий проверенный immutable release;
клиентская БД не восстанавливается без отдельного решения об откате данных.

# Acceptance Criteria

- оба local health endpoint отвечают `200`, правильным environment и build ID;
- test без внешних интеграций имеет общий health `ok`, даже если сохраненный
  source-refresh status ожидаемо требует настройки;
- отдельные systemd timers проверяют health production и test не реже раза в
  минуту и падают при несовпадении environment или backend/static build;
- client-only login отклоняется в test, staff login работает;
- test mutation не появляется в production database;
- test не читает production snapshots/backups и не имеет automatic timers;
- production health `ok`, refresh не активен, current report и Excel доступны;
- параллельные build/promotion/retention не пересекаются, а cleanup сохраняет
  оба active target и минимум один полный rollback release;
- unauthenticated reports/exports остаются закрыты, `.env`, JSON и XLSX не
  раздаются статически;
- DNS и TLS нового домена готовы до передачи ссылки клиенту;
- nginx reload атомарен, неизвестные test routes не отдают legacy static shell;
- `shumeiko-web.service`, порт 8096 и `/etc/shumeiko-web.env` отсутствуют.
- read-only drift check подтверждает совпадение обязательных systemd/nginx
  файлов с Git и отсутствие незарегистрированных prod/test drop-in’ов.

# Changelog

- 2026-07-24: завершено legacy rollback window: unit 8096 и старый
  EnvironmentFile удаляются, rollback выполняется предыдущим immutable release;
  test nginx больше не имеет fallback на старый статический shell, scheduled
  source/archive/retention timers test-контура явно запрещены; добавлена
  read-only проверка deployed-конфигурации на drift без чтения env-файлов.
- 2026-07-19: production unit подключает versioned corporate-proxy login-shell
  drop-in, чтобы AI использовал одобренный proxy из root login profile без
  копирования URL или credentials proxy в Git либо runtime EnvironmentFile.

- 2026-07-18: treat missing/full-refresh configuration as expected test state
  only when external integrations are disabled, while keeping the detailed
  source status visible and real failures degraded.
- 2026-07-18: accepted one shared fail-closed lock for runtime build,
  promotion and dry-run-first release retention with active, rollback, grace,
  path and manifest guards.

- 2026-07-16: закреплена изоляция Python-импортов внутри immutable release;
  runtime bootstrap и его hash запрещают copied `.venv` использовать editable
  checkout рабочего репозитория.
- 2026-07-15: accepted разделение production/test, DB clone sanitization,
  immutable promotion и zero-downtime cutover.
- 2026-07-15: зафиксирована безопасная передача URL отдельной PostgreSQL-роли
  test-контура без вывода секрета.
- 2026-07-15: повторная sanitization сохраняет уже безопасно скопированные
  current report artifacts внутри test root.
