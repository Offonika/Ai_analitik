# AI-аналитик отчетов: пилот Шумейко WB/1C

Локальный серверный проект пилота продукта `AI-аналитик отчетов`.

Заказчик пилота: «Шумейко и партнеры».

Продуктовая рамка: AI-аналитик помогает консалтинговой компании быстрее
готовить клиентские аналитические отчеты: собирает read-only данные, считает
показатели, подсвечивает проблемы, формирует черновик управленческого отчета и
может мониторить изменения. Текущий пилот проверяет эту рамку на задаче
юнит-экономики Wildberries по данным WB и `1С:УНФ`.

Здесь будут храниться только рабочие файлы пилота: настройки, локальные данные и
сгенерированные отчеты. Реальные ключи Wildberries хранятся только в локальном
файле `.env` и не должны попадать в Git, документы, письма или чаты.

# Где хранить ключи WB

Файл:

```text
/opt/shumeyko-partners-wb-unit-economics/.env
```

Формат:

```env
WB_ACCOUNT_1_NAME=
WB_ACCOUNT_1_API_KEY=

WB_ACCOUNT_2_NAME=
WB_ACCOUNT_2_API_KEY=
```

Для двух кабинетов Wildberries заполняются две пары:

- `WB_ACCOUNT_1_NAME` и `WB_ACCOUNT_1_API_KEY`;
- `WB_ACCOUNT_2_NAME` и `WB_ACCOUNT_2_API_KEY`.

Название кабинета можно указать понятным текстом, например название клиента или
юридического лица. API-ключ вставляется только в `.env`.

# Безопасность

- Не хранить реальные ключи WB в README, ТЗ, Markdown-документах или Git.
- Не отправлять ключи в общий чат или открытым письмом.
- Файл `.env` должен быть доступен только владельцу процесса на сервере.
- Если ключ был случайно отправлен в переписке, его нужно перевыпустить в
  кабинете Wildberries.

# Где хранить доступ 1С OData

Доступ к `1С:УНФ` также хранится только в локальном `.env`.

Безопасные имена переменных задокументированы в `.env.example`:

```env
ONEC_ODATA_BASE_URL=
ONEC_ODATA_USERNAME=
ONEC_ODATA_PASSWORD=
ONEC_ODATA_VERIFY_SSL=true
ONEC_ODATA_TIMEOUT_SECONDS=30
```

Реальные URL, логин и пароль не добавлять в Markdown-документы, Git или чат.
Скрипты проекта используют доступ только для `GET`-запросов к согласованным
коллекциям OData.

# Структура

```text
/opt/shumeyko-partners-wb-unit-economics/
  .env              # реальные локальные ключи, не коммитить
  .env.example      # пример без секретов
  config/           # будущие настройки клиентов и методики
  data/             # локальные выгрузки и snapshots, не коммитить
  docs/             # ТЗ, инструкции и spec пилота
  reports/          # Excel-отчеты, не коммитить
```

# Документы

Главная карта документации: `docs/index.md`.

Машинный реестр: `docs/manifest.yml`.

Основные контуры:

- продуктовая рамка: `docs/product-concept-ai-report-analyst.md`;
- Excel MVP: `docs/specs/wb-unit-economics-excel-mvp-implementation.md`;
- DB-first публикация отчетов: `docs/specs/wb-unit-economics-db-first-report-marts.md`;
- web-кабинет и AI: `docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md`;
- source refresh и provider registry:
  `docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md`;
- формулы и ручная сверка: `docs/calculation-formulas.md`;
- сборка и проверка отчета: `docs/runbooks/report-generation.md`;
- эксплуатация web-кабинета: `docs/runbooks/web-cabinet-operations.md`;
- расписание source refresh: `docs/runbooks/source-refresh-schedule.md`;
- клиентская приемка: `docs/client-acceptance-package.md`.

Если непонятно, какой документ читать первым, начинать с `docs/index.md`: там
есть матрица контуров и список обязательных проверок документации.

# Быстрая выгрузка sample из 1С

После настройки `.env` можно выгрузить маленький локальный sample из OData:

```bash
.venv/bin/python scripts/export_onec_odata_samples.py --top 25
```

Результат сохраняется в `data/onec_samples/`. Эта папка локальная и не должна
попадать в Git.

# Быстрая выгрузка карточек WB

Для детализации товаров и маппинга WB <-> 1С можно выгрузить read-only sample
карточек Wildberries:

```bash
.venv/bin/python scripts/export_wb_product_cards.py --limit 100 --max-pages 1 --include-trash
```

Скрипт использует методы WB `content/v2/get/cards/list` и, с флагом
`--include-trash`, `content/v2/get/cards/trash`. Raw JSON сохраняется в
`data/wb_product_cards/`, рядом создается плоский файл `*.flat.json` с
кандидатами для маппинга: `nm_id`, `vendor_code`, `barcode`, `tech_size`,
`subject_name`, `brand`. Основной автоматический маппинг строится по
`nm_id + vendor_code -> Артикул 1С`; `barcode`/`sku` используется как
размерная детализация и контроль, а не как главный ключ.

# Выгрузка сопоставления товаров из 1С

Если в 1С-модуле маркетплейсов уже заполнена форма `Сопоставление товаров`,
выгрузите ее в TXT/табличный текст и положите файлы сюда:

```text
data/onec_marketplace_mapping/
```

При сборке Excel MVP эти файлы используются как основной источник
`sku_mapping`. Автоматическое сопоставление по артикулу 1С остается fallback,
если TXT-выгрузки нет.

# Быстрая выгрузка финансового факта WB

Для первого реального Excel MVP используется новый WB Finance endpoint:

```bash
.venv/bin/python scripts/export_wb_finance.py --period-start 2026-03-01 --period-end 2026-06-17
```

Скрипт использует read-only `POST /api/finance/v1/sales-reports/detailed`,
пагинацию по `rrdId` и сохраняет raw JSON в `data/wb_finance/`. Если WB вернет
401/403/429, это будет отражено в `manifest.json`; такие ошибки нельзя считать
нулевыми продажами.

# Сборка Excel MVP из локальных snapshots

Когда уже есть локальные выгрузки WB Finance, WB cards и 1С OData:

```bash
.venv/bin/python scripts/build_excel_mvp_from_snapshots.py
```

Excel сохраняется в `reports/`. В первом отчете себестоимость из регистра
`Продажи` берется из поля `Себестоимость`: распределенные допрасходы уже внутри
этой суммы и повторно не прибавляются. Листы отчета оформляются как
фильтруемые Excel-таблицы, а статусы качества данных выводятся на русском языке.
В видимых колонках Excel кабинеты WB подписываются названием организации 1С;
технические `WB_ACCOUNT_*` остаются только во внутренних snapshots и расчетных
ключах.

# Загрузка WB Finance в локальный Postgres

Для дальнейшего расчета юнит-экономики из базы можно переложить уже скачанные
raw snapshots WB Finance в Postgres:

```bash
.venv/bin/python scripts/load_wb_finance_postgres.py \
  --db-name shumeyko_wb_unit_economics \
  --port 55433 \
  --wb-finance-dir data/wb_finance/<timestamp> \
  --onec-dir data/onec_samples/<timestamp>
```

Скрипт не делает новых запросов к WB и не читает `.env`: он берет только
локальные `manifest.json` и `*.raw.json`. В Postgres сохраняется полный исходный
объект строки в `jsonb`, typed-поля для расчета и недельное представление
`wb_unit_economics.v_wb_finance_weekly_totals`.

После загрузки можно собрать Excel MVP уже из Postgres-слоя:

```bash
.venv/bin/python scripts/build_excel_mvp_from_snapshots.py \
  --wb-finance-source postgres \
  --postgres-db-name shumeyko_wb_unit_economics \
  --postgres-port 55433
```

# Авторизованный web-кабинет v2

Web-кабинет v2 не публикует клиентские JSON/Excel artifacts напрямую. Данные
импортируются в PostgreSQL/локальную runtime-БД и отдаются только через
авторизованный FastAPI API.

Минимальный локальный запуск:

```bash
.venv/bin/python scripts/import_web_report_from_excel.py \
  --database-url sqlite:///data/web/shumeyko_web.sqlite3 \
  --workbook reports/shumeyko_wb_excel_mvp.xlsx \
  --admin-email admin@example.local \
  --admin-password-env SHUMEYKO_BOOTSTRAP_PASSWORD

SHUMEYKO_DATABASE_URL=sqlite:///data/web/shumeyko_web.sqlite3 \
  .venv/bin/uvicorn wb_unit_economics.web.app:app --host 127.0.0.1 --port 8096
```

Production-путь использует PostgreSQL, nginx `/api/*`, HTTPS и session cookie.
`OPENAI_API_KEY`/`SHUMEYKO_OPENAI_API_KEY`, пароли пользователей и доступы
WB/1С хранятся только в закрытом runtime окружении, не в Git и не в Markdown.

Для v2.1 эксплуатационные команды собраны в
`docs/runbooks/web-cabinet-operations.md`: server-side пользователи, импорт
нового `report_run`, AI/live-checks, backup, monitor и deployment smoke.
