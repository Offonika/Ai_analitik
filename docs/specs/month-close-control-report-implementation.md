---
spec_id: "workspace-shumeyko-month-close-control-report-implementation"
title: "Контроль закрытия месяца: web-сценарий и Excel"
doc_type: spec
domain: "accounting-operations"
status: accepted
owner: "engineering"
audience: ["engineering", "consultant", "operations", "accountant"]
source_of_truth: true
truth_scope: "month-close-control"
truth_priority: 100
related_code:
  - scripts/month_close_cabinet_settings.py
  - scripts/probe_onec_month_close_osv.py
  - scripts/build_onec_month_close_audit_pack.py
  - src/wb_unit_economics/onec_odata.py
related_tests:
  - tests/test_month_close_cabinet_settings.py
  - tests/test_onec_month_close_osv_probe.py
  - tests/test_onec_month_close_audit_pack.py
contracts:
  - month_close_control_report
depends_on:
  - docs/specs/multi-report-cabinet-implementation.md
  - docs/specs/month-close-control-pilot.md
  - docs/decisions/2026-07-14-accounting-reports-accountant-questions.md
related_specs:
  - docs/specs/tax-load-report-implementation.md
  - docs/specs/accounting-reports-smart-process-onepage.md
supersedes:
  - docs/specs/month-close-control-pilot.md
rollout_required: true
updated_at: "2026-07-16"
---

# Статус документа

Это accepted implementation spec staff-only advisory v1 поверх завершенного
discovery-пилота. Она заменяет `docs/specs/month-close-control-pilot.md` как
implementation target, но не разрешает `ready_to_close`, подтверждение
бухгалтера, enforced checks или клиентскую публикацию до решений из decision
document. Статус `implemented` возвращается только после сквозной проверки
реального evidence из read-only 1С в Web и Excel.

Согласовано:

- отдельный `report_kind = month_close_control`;
- основной период — календарный месяц;
- первая версия доступна `consultant/admin`;
- результат — web-сценарий и Excel из одного report run;
- в первом rollout налоговые факты и клиентский вывод ведет один ответственный
  специалист, при этом подтверждение фактов и утверждение текста фиксируются
  раздельно;
- FinKoper не подключается на первом этапе;
- полнота бизнес-проверок сначала advisory: предупреждения видны, но не мешают
  тестировать внутренний draft и Excel.

# Goal

Дать консультанту воспроизводимый read-only контроль закрытия месяца по данным
1С и приложенным подтверждениям: показать, что проверено автоматически, что
подтверждено человеком, где есть расхождение и какой следующий шаг нужен.

Сценарий не закрывает месяц в 1С и не заменяет решение бухгалтера. Его результат
— проверочный пакет для консультанта и бухгалтера.

# Scope

Входит:

- календарный месяц и организация 1С;
- онлайн-ОСВ или ее детерминированная реконструкция;
- ЕНС и налоговые расчеты;
- НДС для применимого налогового профиля;
- банк и движения денежных средств;
- ручные операции и корректировки;
- карта покрытия регламента;
- вложения и ручные подтверждения без FinKoper-интеграции;
- риски, расхождения и дозапросы;
- advisory-рекомендация по готовности закрытия;
- web-представление и Excel artifact;
- audit источников, запуска, экспорта и подтверждения бухгалтера.

# Out Of Scope

Не входит:

- проведение или корректировка документов 1С;
- запуск штатной процедуры закрытия месяца;
- отправка деклараций, платежей или сообщений;
- запись задач и статусов в FinKoper;
- автоматическое подтверждение бухгалтера;
- клиентская публикация первой версии;
- жесткая блокировка staff draft из-за неполного бизнес-чек-листа;
- поддержка любого налогового режима без отдельной методики.

# Users And Ownership

- `responsible_specialist` в первом rollout совмещает обязанности бухгалтера и
  консультанта: подтверждает фактические показатели, объясняет расхождения,
  проверяет coverage и утверждает клиентский вывод.
- Два действия сохраняются раздельно в audit и могут иметь один `user_id`.
- `admin` обеспечивает доступность read-only интеграций и storage, но не
  подтверждает бухгалтерские факты.
- `client_*` не получает этот вид в первой версии.

Подтверждение бухгалтера должно хранить пользователя, время, период,
организацию, версию отчета и безопасный комментарий без секретов или raw data.

# Smart Process Linkage

ONEPAGE операционного процесса задана в
`docs/specs/accounting-reports-smart-process-onepage.md`.

Один `month_close_control` связывается с внутренней задачей общей карточки
клиента, организации и календарного месяца. Он не отправляется клиенту и не
может быть заменен артефактом `tax_load`. Статус, `report_id`, версия, проверки
и замечания этой задачи хранятся отдельно.

Смарт-процесс реализуется как отдельный модуль web-кабинета по принятой
ONEPAGE-концепции и не входит в эту report spec; запись во внешние CRM,
включая FinKoper, отнесена ко второму этапу. До реализации модуля связь может
фиксироваться вручную безопасным идентификатором или ссылкой без raw client
data.

Сроки создания карточки, выполнения двух задач, проверки руководителем,
контрольного контакта и закрытия к зарплате определяет ONEPAGE. Эта report spec
не переопределяет workflow-SLA и отвечает только за формирование и проверку
`month_close_control`.

Рекомендация отчета `ready_to_close` завершает только задачу
`month_close_control`. Она не является стадией всей карточки: соответствующий
системный идентификатор Канбана — `ready_for_payroll_close`.

# Period And Source Coverage

`report_period` всегда является полным календарным месяцем. Отчет строится
для явной организации 1С; current и история ведутся по связке
`tenant + client + report_kind + organization_id` по правилу spec
многотипного кабинета, поэтому отчеты разных организаций одного клиента не
вытесняют друг друга. Фактическое `source_coverage` хранится отдельно по
каждому источнику.

Если источник покрывает только часть месяца или недоступен:

- показатель остается `null` или получает явный статус;
- отсутствие не интерпретируется как ноль;
- web и Excel показывают период ограничения;
- общий отчет может быть создан как предварительный staff draft.

# Read-Only Sources

Основной порядок источников ОСВ:

1. `AccountingRegister_Управленческий/BalanceAndTurnovers(...)`;
2. реконструкция по `AccountingRegister_Управленческий_RecordType` и плану
   счетов;
3. разовая сверочная выгрузка штатной ОСВ только для проверки онлайн-расчета.

Если публикация 1С отвечает HTTP 500 на server-side `$filter` бухгалтерского
регистра, worker не считает источник пустым. Он выполняет совместимый GET-only
проход по страницам `RecordType` без фильтра, сохраняет raw-страницы только в
локальном snapshot и детерминированно агрегирует остатки и обороты по
`organization_id + account`. В evidence и API попадает только нормализованный
агрегат со ссылкой и SHA-256 raw manifest. GET использует проверенную публикацией
минимальную `$select`-проекцию: период, активность, организация, дебетовый и
кредитовый счет, сумма; посторонние поля проводки не загружаются. RecordType
читается до доказуемой границы выбранного периода. Worker задает серверу явный
стабильный `$orderby=Period asc,Recorder asc,LineNumber asc`; live GET этой
публикации подтвердил поддержку составного порядка. Поля `Recorder` и
`LineNumber` включены в `$select` только как уникальный ключ пагинации и не
попадают в агрегированный API. После первой полностью
следующей за периодом страницы чтение останавливается: все строки для входящих
остатков и оборотов уже находятся в raw lineage. Для малых бухгалтерских
регистров применяется тот же `Period + Recorder + LineNumber`, для документов —
`Date + Ref_Key`, без server-side period filter. Лимит бухгалтерской генерации должен
позволять сначала дойти
до выбранного окна и не ограничивается общим cap в 200 страниц. Все полученные
GET-страницы остаются raw evidence, но объединенный нормализуемый файл содержит
только строки запрошенного периода; организация повторно отбирается при
materialization. Поэтому несовместимый OData-фильтр не меняет границы отчета,
многолетняя история не попадает целиком в payload и крупный raw snapshot не
лишает evidence строк выбранного месяца.

Размеры страниц фиксируются только после live GET-проверки той же публикации:
до 5000 строк для локальных налоговых регистров и до 10000 строк для RecordType
с минимальной `$select`-проекцией. Это уменьшает число дорогих запросов со
`$skip`, не меняя набор raw-строк, границы периода или формулы агрегации.
Переносимый default RecordType остается 10000; отдельная настройка
`SHUMEYKO_ACCOUNTING_RECORDTYPE_PAGE_SIZE` разрешает production worker этого
пилота использовать подтвержденные live-пробой 50000 строк.

Дополнительные группы:

- ЕНС и расчеты по налогам;
- покупки, продажи, предъявленный НДС, авансы и применимые разделы декларации;
- движения денег, банк и взаиморасчеты;
- доходы, расходы, продажи и закупки;
- ручные операции;
- безопасные ручные подтверждения и вложения.

Raw OData rows, клиентские URL, учетные данные, скрины и Excel клиента не
публикуются через web API и не попадают в Markdown или Git.

# Proposed Contract

`month_close_control_report` содержит:

```text
meta:
  report_id, tenant_id, client_id, report_kind
  organization_id, period_start, period_end
  methodology_version, generated_at
  calculation_status, publication_status
source_coverage[]:
  source_kind, period_start, period_end, status, snapshot_id
controls[]:
  control_code, section, title, status
  source_kind, evidence_status, issue_code, next_action
osv_summary:
  source_kind, reconciliation_status, mismatch_count
osv_rows[]:
  account_code, account_name, opening_debit, opening_credit
  debit_turnover, credit_turnover, closing_debit, closing_credit
  reconciliation_status, *_delta
tax_summary, ens_summary, vat_summary, bank_summary
manual_operations_summary
confirmations[]:
  confirmation_kind, status, confirmed_by, confirmed_at
issues[]:
  code, severity, section, message, next_action
business_recommendation
accountant_approval
```

Версия сохраненного контракта первой исправленной реализации —
`month-close-control-report-v2`. В `meta` обязательны
`source_refresh_run_id`, `source_snapshot_set_id` и `evidence_sha256`.
Отчет использует evidence только собственного generation run.

Правила ОСВ v2:

- рабочий RecordType fallback используется, если BalanceAndTurnovers имеет
  `source_error` или не дал валидного кандидата;
- без эталонной ОСВ строки получают `not_checked`, а не `matched`;
- счета только из эталона добавляются со статусом `missing`;
- повторяющиеся строки одного кода счета агрегируются детерминированно;
- любая ненулевая дельта дает `warning`, missing остается `null`.

Стабильные статусы control item:

- `confirmed` — подтверждено источником или аудируемым человеком;
- `partial` — покрыто не полностью;
- `not_confirmed` — доказательства нет;
- `not_applicable` — неприменимо с указанным основанием;
- `source_error` — источник не удалось прочитать или проверить.

`evidence_status` хранится отдельно от результата суммы, чтобы приложенный файл
или комментарий не превращал неподтвержденную цифру в подтвержденную.

# Business Recommendation And Soft Gates

Предварительная рекомендация:

- `ready_to_close` — все настроенные обязательные проверки подтверждены;
- `review_required` — есть вопросы, но факты позволяют продолжить ручную
  проверку;
- `cannot_confirm` — данных недостаточно или есть существенное расхождение.

На первом этапе это advisory-поле, а не команда и не блокировка работы в 1С.
До ответов на вопросы 1–4 значение `ready_to_close` зарезервировано и не
выставляется: staff может получить `review_required` или `cannot_confirm`,
открыть web-draft и скачать Excel.

Жестко блокируются только:

- нарушение tenant boundary;
- невалидный report contract;
- потеря lineage или подмена периода;
- попытка записи во внешнюю систему;
- утечка секретов или raw client data.

Неполный чек-лист, отсутствующий скрин, неподтвержденный НДС или расхождение ОСВ
дают предупреждение и `cannot_confirm`/`review_required`, но не мешают
тестированию внутреннего сценария.

# Web Scenario

Общая оболочка остается единой:

- `Обзор` — период, организация, recommendation, coverage, основные риски;
- `Проверки` — чек-лист регламента по секциям и следующий шаг;
- `Таблицы` — ОСВ, ЕНС/налоги, НДС, банк, ручные операции, подтверждения;
- `Инструкция` — порядок проверки и роли без raw данных.

Глобальные фильтры:

- клиент;
- вид отчета;
- календарный месяц;
- организация 1С.

Marketplace cabinet не показывается. Переключение периода не меняет
существующий report run; пользователь выбирает готовую ревизию или формирует
новый draft.

# Excel Artifact

Excel строится из того же `report_id`, что и web, и содержит минимум:

- `Сводка закрытия`;
- `Покрытие регламента`;
- `ОСВ`;
- `ЕНС и налоги`;
- `НДС`;
- `Банк`;
- `Ручные операции`;
- `Подтверждения`;
- `Риски и дозапросы`;
- `Источники и статус`.

В workbook указываются `report_id`, период, организация, версия методики,
фактическое покрытие и пометка `Предварительный`, если есть warnings. Web и
Excel должны сходиться по статусам и агрегатам.

# Calculation And Reconciliation Rules

- ОСВ рассчитывается детерминированно из выбранного source snapshot.
- Parent/subaccount строки не суммируются наивно и не должны давать двойной
  счет.
- Сверка сравнивает одинаковый период, организацию, счет и набор колонок.
- Missing source не становится нулевым остатком или оборотом.
- `BalanceAndTurnovers` выбирается первым; нормализованный `RecordType` служит
  fallback. Любая ненулевая дельта получает `warning`, а невозможная из-за
  missing-значения дельта остается `null`.
- Налоговый профиль определяется по accepted tax-methodology; неизвестный
  профиль блокирует только достоверность соответствующих налоговых выводов.
- AI может объяснить уже рассчитанные расхождения, но не придумывает причину и
  не меняет recommendation.

# Security, Tenant Isolation And Audit

- Все live-запросы к 1С остаются GET/read-only.
- Доступ проверяется по `tenant_id`, `client_id`, `organization_id` и
  `report_id`.
- Подтверждения и artifacts не доступны другому tenant.
- Audit фиксирует запуск, source snapshot ids, экспорт, просмотр и подтверждение
  бухгалтера.
- Retention не удаляет evidence current report и подтвержденной ревизии без
  отдельного правила.

# Errors And Edge Cases

- `BalanceAndTurnovers` недоступен: использовать проверенный fallback и показать
  фактический источник.
- `BalanceAndTurnovers` и RecordType fallback не дали ни одной строки ОСВ:
  завершить generation как source-integrity error и не создавать новый current.
- Онлайн-ОСВ расходится со штатной: сохранить mismatch и дозапрос, не выбирать
  победителя молча.
- НДС недоступен через OData: статус `not_confirmed`, сумма не считается
  подтвержденной.
- Нет обязательного вложения: advisory warning до утверждения чек-листа.
- Организация или период не совпадает: не объединять факты.
- Повторный запуск по тем же snapshots и методике должен дать тот же результат.

# Acceptance Criteria

- Отчет создается только для полного календарного месяца и явной организации.
- ОСВ использует зафиксированный источник и проходит repeatability test.
- RecordType fallback агрегирует каждую организацию независимо и не требует
  server-side фильтра по периоду.
- Для каждого пункта регламента есть status, evidence status и next action.
- Missing/partial данные не заменяются нулями.
- Web и Excel построены из одного `report_id` и сходятся.
- Staff может тестировать draft при business warnings.
- Security/read-only/tenant нарушения остаются blocking.
- Подтверждение бухгалтерских фактов и утверждение клиентского вывода являются
  разными audit-действиями; в первом rollout их может выполнять один
  ответственный специалист.
- Клиентская роль не видит сценарий первой версии.

# Test Plan

- unit tests выбора источника ОСВ и fallback;
- contract tests `month_close_control_report`;
- calendar-month and source-coverage tests;
- parent/subaccount reconciliation tests;
- missing/partial/VAT status tests без zero coercion;
- accountant approval audit tests;
- web role and tenant-boundary tests;
- web/Excel parity smoke;
- advisory warnings allow staff draft/export;
- source-error BalanceAndTurnovers не перекрывает рабочий fallback;
- отсутствие эталона дает `not_checked`, reference-only счет — `missing`,
  дубли кода счета агрегируются;
- e2e строит evidence из обезличенных raw строк 1С, а не из готового
  `normalizedEvidence`;
- hard security failures remain blocking;
- `.venv/bin/python scripts/validate_specs.py`;
- `.venv/bin/python scripts/validate_docs_manifest.py`;
- `.venv/bin/python scripts/validate_llm_docs.py`;
- `.venv/bin/python scripts/validate_no_secrets.py`.

# Rollout And Rollback

1. Создать contract/marts из существующего audit-pack calculation.
2. Проверить parity с локальным Excel пилота без публикации raw data.
3. Включить staff-only web-сценарий в advisory mode.
4. После нескольких месяцев тестирования согласовать подтверждения и enforced
   rules отдельным изменением spec.

Rollback отключает `month_close_control` в registry. Источники и созданные
report runs остаются для audit, юнит-экономика не меняется.

# Deferred Decisions

- Какие доказательства обязательны для каждого пункта регламента.
- Каким способом бухгалтер подтверждает факты в первой версии.
- Как закрывается известное расхождение ОСВ и какие дельты допустимы.
- Какой read-only источник окончательно подтверждает НДС.
- Когда и какие advisory rules переводятся в enforced.
- Нужна ли будущая FinKoper-интеграция и какой read-only интерфейс доступен.

Вопросы, требующие ответа бухгалтера, вынесены с владельцем и сроком в
`docs/decisions/2026-07-14-accounting-reports-accountant-questions.md`.
До ответов `ready_to_close` и окончательное подтверждение недоступны, но
вопросы не блокируют accepted staff-only advisory v1.

# Changelog

- 2026-07-16: уточнено, что нормативные сроки и workflow-переходы определяет
  ONEPAGE, report spec не переопределяет операционный SLA, а отчетный
  `ready_to_close` отделен от Канбан-стадии `ready_for_payroll_close`.
- 2026-07-16: уточнена целевая система смарт-процесса: отдельный модуль
  web-кабинета без внешних интеграций; интеграция с FinKoper перенесена на
  второй этап, упоминание Bitrix удалено.
- 2026-07-16: report spec связана с accepted ONEPAGE смарт-процесса; в первом
  rollout бухгалтер и консультант объединены в одного ответственного
  специалиста, а подтверждение фактов и утверждение текста остаются раздельными
  audit-действиями.
- 2026-07-14: стабильный canary подтвердил нулевые дубли ключей, но обнаружил
  drift исходника относительно audit-pack: 346712 текущих майских проводок
  против 189401, включая 157333 новых уникальных ключа и 22 удаленных. Hash и
  Excel parity прошли, бухгалтерская приемка заблокирована до свежей штатной
  ОСВ; canary-валидатор теперь проверяет expected aggregate baseline кодом.
- 2026-07-14: live GET подтвердил RecordType-страницу 50000 строк; размер
  вынесен в отдельную настройку с default 10000 и production override 50000,
  чтобы не навязывать проверенный для одного пилота лимит другим публикациям.
- 2026-07-14: сверка canary выявила дубли и пропуски при неуникальном
  `$orderby=Period asc`; live GET подтвердил стабильный составной порядок
  `Period + Recorder + LineNumber`. Невалидный report оставлен скрытым и снят с
  current, приемка требует нового canary.
- 2026-07-14: live GET подтвердил страницы 5000 строк для налогового регистра и
  10000 строк для минимальной RecordType-проекции; worker использует эти
  проверенные размеры, чтобы не выполнять сотни дорогих `$skip`-запросов.
- 2026-07-14: live GET подтвердил `$orderby=Period asc`; первоначальная версия
  оказалась недостаточно стабильной для `$skip` при одинаковых датах и была
  заменена составным уникальным порядком.
- 2026-07-14: live GET подтвердил поддержку минимальной `$select`-проекции
  RecordType; fallback больше не переносит неиспользуемые поля проводок, при
  этом read-only граница и полный проход до конца выбранного периода сохранены.
- 2026-07-14: корректный canary показал, что налоговый регистр до лимита 200
  страниц доходил только до 2026-03-29 и не включал контрольный май. Для
  бухгалтерской генерации cap поднят до 1000 страниц с ранней остановкой после
  выбранного окна; объединенный файл ограничен самим периодом, raw GET-страницы
  сохранены для lineage.
- 2026-07-14: малые налоговые и банковские источники получили локальную
  period-window остановку после выбранного месяца. Для RecordType fallback
  ранняя остановка на нативном порядке первоначально не применялась из-за
  необходимости входящих остатков.
- 2026-07-14: lineage-аудит показал, что первые скрытые canary были ошибочно
  запущены в общем tenant `shumeyko`, а audit-pack относится к отдельному
  tenant клиента. Их бухгалтерская сверка признана невалидной; добавлено
  безопасное разрешение tenant/client по уникальному имени и запущен новый
  canary в правильном контуре.
- 2026-07-14: технический canary в ошибочно выбранном tenant сформировал
  непустые evidence и подтвердил одинаковый SHA-256 Web/Excel, но его
  бухгалтерские показатели не используются как приемочные из-за неверного
  client scope.
- 2026-07-14: второй скрытый canary показал неполноту ранней остановки
  RecordType по датам страниц без заданного порядка; нативная остановка была
  отменена, а затем заменена серверно гарантированным `Period asc`.
- 2026-07-14: первый production canary выявил HTTP 500 на server-side фильтрах
  бухгалтерских регистров и пустую ОСВ; вид снова выключен. В spec закреплены
  совместимый GET-only RecordType fallback, локальный отбор периода и запрет
  создавать current без строк ОСВ.
- 2026-07-14: код и schema v2 развернуты с выключенным
  `month_close_control`; статус остается `accepted` до сверки реального
  контрольного месяца с audit-pack.
- 2026-07-14: после аудита статус возвращен в `accepted`; обязательны
  production-материализация evidence, безопасный fallback ОСВ и сквозная
  проверка по реальному обезличенному снимку 1С.
- 2026-07-14: контракт повышен до `month-close-control-report-v2`; закреплены
  lineage evidence, `not_checked` без эталона, reference-only строки и
  детерминированная агрегация дублей.
- 2026-07-14: реализованы детерминированный выбор ОСВ/fallback, сверка дельт,
  staff-only web-сценарий и Excel из единого сохраненного payload.
- 2026-07-14: spec принята для staff-only advisory v1; `ready_to_close`
  зарезервирован до ответов бухгалтера, discovery-пилот superseded.
- 2026-07-14: уточнения после ревью: current по организации 1С, фиксация
  судьбы пилотной спеки при переводе в accepted и ссылка на список вопросов
  бухгалтеру.
- 2026-07-14: создан draft web + Excel сценария; закреплены календарный месяц,
  роли бухгалтера и консультанта, staff-only доступ, ручные подтверждения без
  FinKoper и мягкие бизнес-проверки первой версии.
