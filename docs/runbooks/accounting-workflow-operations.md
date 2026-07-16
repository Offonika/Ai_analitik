---
title: "Эксплуатация смарт-процесса бухгалтерских отчетов"
doc_type: runbook
domain: "accounting-operations"
audience: ["engineering", "operations", "consultant"]
status: active
source_of_truth: false
source_spec: "docs/specs/accounting-reports-smart-process-onepage.md"
updated_at: "2026-07-16"
---

# Эксплуатация смарт-процесса бухгалтерских отчетов

Runbook относится к внутреннему процессу закрытия месяца и отчета по налоговой
нагрузке. Канонические бизнес-правила находятся в
`docs/specs/accounting-reports-smart-process-onepage.md`.

# Границы

- модуль доступен только сотрудникам кабинета;
- сервис не отправляет отчеты клиенту автоматически;
- сервис не пишет в 1С, FinKoper и внешние CRM;
- evidence хранится локально вне Git и выдается только после повторной проверки
  сессии, роли и tenant;
- production-флаги до отдельной приемки остаются выключенными.

# Предварительные условия

Перед тестовым или production-включением:

1. Применить идемпотентную миграцию:

   ```bash
   .venv/bin/python scripts/migrate_web_database.py
   ```

2. Убедиться, что в реестре активных `client_companies` заполнен
   `onec_organization_id`, а у ответственного есть роль `consultant`.
3. В тестовом контуре включить оба вида отчетов:
   `month_close_control,tax_load`. В production это допускается только после
   приемки их собственных report-spec.
4. Настроить производственный календарь и защищенный каталог evidence. Каталог
   должен принадлежать пользователю web-сервиса, иметь минимально необходимые
   права и не находиться внутри Git-репозитория.
5. Администратор через `POST /api/accounting-workflows/supervisors` выдает
   отдельное разрешение руководителя. Роль `admin` без этого разрешения не дает
   права отменять и закрывать карточки.

# Конфигурация

Безопасные переменные перечислены в `.env.example`:

```text
SHUMEYKO_ACCOUNTING_WORKFLOW_ENABLED=false
SHUMEYKO_ACCOUNTING_WORKFLOW_SCHEDULER_ENABLED=false
SHUMEYKO_ACCOUNTING_WORKFLOW_CALENDAR_CONFIGURED=false
SHUMEYKO_ACCOUNTING_WORKFLOW_NON_WORKING_DATES=
SHUMEYKO_ACCOUNTING_WORKFLOW_WORKING_DATES=
SHUMEYKO_ACCOUNTING_WORKFLOW_EVIDENCE_ROOT=data/accounting_workflow_evidence
SHUMEYKO_ACCOUNTING_WORKFLOW_EVIDENCE_MAX_BYTES=5242880
```

Даты календаря задаются списком `YYYY-MM-DD` через запятую. Переменная
`NON_WORKING_DATES` добавляет праздники и переносы выходных,
`WORKING_DATES` — официальные рабочие выходные. В production одного значения
`CALENDAR_CONFIGURED=true` недостаточно: список должен быть сверён с принятым
производственным календарем.

# Dry-run и расписание

Без записи данных проверить выбранный месяц:

```bash
.venv/bin/python scripts/run_accounting_workflow_scheduler.py \
  --tenant-id shumeyko \
  --period-month 2026-06 \
  --force-monthly \
  --dry-run \
  --json
```

Обычный запуск выполняется ежедневно. В последний календарный день текущего
месяца он идемпотентно создает карточки, в остальные дни только переводит
просроченные follow-up в `contact_due` или `escalated`:

```bash
.venv/bin/python scripts/run_accounting_workflow_scheduler.py --json
```

Внешний timer должен вызывать команду один раз в день после создания backup БД.
Повторный запуск безопасен: monthly-run возвращает существующую актуальную
карточку цепочки и не создает дубликат.

# Ручная приемка пилота

На одной связке клиент + организация + месяц проверить:

1. Создана одна карточка и ровно две задачи.
2. Ответственный и руководитель назначены до стадии `data_collection`.
3. Каждая задача принимает только current-ревизию своего `report_kind`, периода,
   клиента и организации, а `payloadSha256` совпадает.
4. `month_close_control` завершается только с `ready_to_close`; `tax_load` —
   после раздельного подтверждения фактов и текста и отметки финальной ревизии.
5. Канбан и таблица показывают одинаковую стадию, задачи и SLA.
6. PNG, JPEG или PDF evidence загружается в защищенный каталог; неверный тип,
   сигнатура или превышение лимита отклоняются.
7. Финальная ручная отправка создает delivery и follow-up через два рабочих дня,
   после чего карточка автоматически становится `ready_for_payroll_close`.
8. Закрытие выполняет только пользователь с разрешением руководителя. Клиентская
   роль не видит экран, API и evidence.
9. Новая current-ревизия возвращает связанную задачу и карточку в `rework`, а
   старое delivery аннулируется.

# Наблюдение

Проверять агрегаты без содержимого клиентских отчетов:

- количество новых, дедуплицированных и пропущенных карточек в выводе scheduler;
- карточки с `overdue=true` и `hardOverdue=true` в staff-only таблице;
- follow-up со статусами `contact_due` и `escalated`;
- события `accounting_workflow_*` в журнале аудита;
- отсутствие файлов evidence в Git и доступ каталога только сервисному
  пользователю.

# Rollback

1. Установить `SHUMEYKO_ACCOUNTING_WORKFLOW_SCHEDULER_ENABLED=false`.
2. Установить `SHUMEYKO_ACCOUNTING_WORKFLOW_ENABLED=false`.
3. Перезапустить web-сервис и отключить внешний timer.
4. Проверить, что `/accounting-workflows` и API модуля недоступны.

Rollback не удаляет карточки, задачи, audit и evidence. Схему БД назад не
откатывать: данные нужны для расследования и повторного включения. Отчеты
`month_close_control` и `tax_load` продолжают жить по собственным feature-флагам
и правилам публикации.
