---
title: "Production rollout MVP логистики (первая очередь)"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-logistics-cost-analysis-implementation.md"
updated_at: "2026-07-19"
---

# Назначение

Пошаговый план вывода готового фактического MVP логистики (`wb-logistics-v5`,
первая очередь) на production: сначала staff (master-флаг), после приёмки —
клиентская роль. Дополняет
`docs/runbooks/web-cabinet-operations.md` (раздел «Staff-ready анализ логистики»,
там задокументирован только test-rollout) и operational state
`docs/runbooks/wb-logistics-v4-continuation.md`.

Канонический источник истины — accepted
`docs/specs/wb-logistics-cost-analysis-implementation.md`; при расхождении
действует он и раздел `Rollout And Rollback` спека.

# Кто выполняет и границы

Каждый шаг, меняющий production (флаги, миграция, рестарт сервиса, публикация
клиенту), выполняет оператор с доступом к серверу и **явным разрешением**.
Автоматический агент production не переключает. Внешние интеграции остаются
read-only; write-операции в WB/1С запрещены.

До 2026-07-18 production client rollout числился «вне текущего этапа». Этот
runbook переводит его в управляемый шаг; он не отменяет требование отдельного
разрешения и повторной проверки состояния сред.

# Контуры

- production: `shumeiko-web-prod.service`, `127.0.0.1:8097`,
  `/etc/shumeiko-web-prod.env`, `https://analitika.offonika.ru`;
- test: `shumeiko-web-test.service`, `127.0.0.1:8098`,
  `https://shumeiko.offonika.ru`.

Флаги: `SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED` (master),
`SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED` (клиентская роль),
`SHUMEYKO_DB_FIRST_REPORTS_ENABLED` (обязателен для master).

# Шаг 0. Проверить текущее состояние (обязательно)

Code defaults `false/false` не являются доказательством состояния среды.
Задокументированное на 2026-07-18: production на прежнем runtime, клиентский флаг
выключен; test — master+client включены. **Перед действиями переподтвердить
фактическое состояние production свежим evidence:**

```bash
# health и окружение
curl --noproxy '*' -fsS https://analitika.offonika.ru/api/health
# фактические флаги роли (под staff-сессией)
# /api/me должен показать master/client flags production
```

Зафиксировать: runtime/build id, master/client флаги, применена ли миграция
`2026_07_18_logistics_profit_link_v5`, `SHUMEYKO_DB_FIRST_REPORTS_ENABLED`.
Снять backup (`shumeiko-web-backup.service`) до изменений.

# Шаг 1. Предусловия

- Получено явное разрешение на production и клиентскую публикацию.
- На production применена additive-миграция `2026_07_18_logistics_profit_link_v5`
  через штатный `init_db`.
- `SHUMEYKO_DB_FIRST_REPORTS_ENABLED=true` на production. Master-флаг без
  DB-first — ошибка конфигурации; source refresh не запускается.
- Есть свежий verified read-only snapshot клиента на production для сборки v5.

# Шаг 2. Включить master-флаг (staff)

1. В `/etc/shumeiko-web-prod.env` установить
   `SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=true` (клиентский флаг пока `false`).
2. Перезапустить сервис:

```bash
sudo systemctl restart shumeiko-web-prod.service
curl --noproxy '*' -fsS https://analitika.offonika.ru/api/health
```

3. Под consultant/admin проверить `/api/me`: master flag `true`, client flag
   `false`.

# Шаг 3. Собрать v5-отчёт из сохранённого снимка

1. Запустить новый `full` source refresh с read-only WB-доступом. Витрина
   строится из сохранённых `source_snapshot_rows` (или verified
   file-authoritative), а не из ответа API на лету.
2. Открыть новый draft-отчёт под consultant/admin. Контекст должен иметь
   `methodologyVersion=wb-logistics-v5`, `chainKeyVersion=wb-order-product-v1`,
   `data_status=ready`. `blocked`, отсутствующий или v1–v4 контекст нельзя
   обходить fallback-ключом или ручной публикацией; для исправления — новый
   report run.

# Шаг 4. Staff-проверка (без клиента)

- `reportCoverage`: source/report invalid-строки, `chainDimensionConflicts`,
  `invalidSourcePayloadShapes`, `sourceIdentityErrors`,
  `sourceRevisionConflicts`, `scopeMismatches`, unmatched dimensions,
  `maxDimensionDelta`.
- Сверить точные календарные срезы, компоненты и несколько обезличенных цепочек
  по `productRef`. На части недели логистика точная, финансовые KPI — `null`.
- HTTP 400 `invalid_logistics_period` для инвертированного диапазона и дат вне
  периода report run.
- Логистика summary/products/orders под staff — HTTP 200; старый необязательный
  отчёт — `needs_rebuild` без нового publication blocker.

Публиковать отчёт как current только штатным audited-механизмом; сохранённые
контрольные задачи (напр. `monthly_reconciliation_unresolved`, теперь advisory)
не скрывать.

# Шаг 5. Включить клиентскую роль (после приёмки)

Только после staff-приёмки и **отдельного разрешения**:

1. Установить `SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED=true` в
   `/etc/shumeiko-web-prod.env`.
2. Перезапустить `shumeiko-web-prod.service`, проверить `/api/health`.

# Шаг 6. Клиентская проверка

Под client-ролью на текущем v5-отчёте:

- `/api/me`: client flag `true`;
- logistics summary/products — HTTP 200, `dataStatus=ready`,
  `sliceStatus=partial`, финансовый статус `not_available_missing_profit_link`,
  финансовые KPI `null`, рейтинги пусты, product rows доступны;
- staff-only orders и чужой/старый draft — HTTP 404;
- deep-link `#tables/logistics` открывается без лишнего клика; desktop и mobile
  без overflow и console/page/network ошибок.

# Шаг 7. Health и smoke

- `/api/health` — `status=ok`, `runtimeEnvironment=production`, одинаковые
  `backendBuildId`/`staticBuildId`; health timer завершился `success`.
- Пройти `Deployment Smoke` из `web-cabinet-operations.md`.
- Временные staff/client сессии после smoke удалить.

# Rollback

- Частичный (скрыть у клиента): `SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED=false`
  + рестарт — раздел остаётся у staff.
- Полный: `SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=false` + рестарт web/worker —
  скрывает маршруты и раздел.

Rollback не меняет существующие отчёты и не удаляет добавочные витрины. Он не
снимает publication blocker с report run, который обязан был пройти gate, но не
прошёл; для исправления — новый report run, повторный импорт того же `report_id`
запрещён. Внешние источники при rollout и rollback не изменяются.

# Безопасность

- Интеграции read-only; write в WB/1С запрещены.
- Raw payload, внешние order-id, source hashes, токены и секреты не появляются в
  API, UI, AI-контексте и логах.
- Клиентские идентификаторы, объёмы и скриншоты приёмки остаются локальным
  operational evidence и не переносятся в Git/Markdown.
- Секреты не читать и не печатать; env-файлы правит оператор на сервере.

# После rollout

Зафиксировать результат отдельным docs-only change (как для test-rollout),
обновив `wb-logistics-v4-continuation.md` фактическим состоянием production с
датой. Не переносить клиентские агрегаты в документацию.
