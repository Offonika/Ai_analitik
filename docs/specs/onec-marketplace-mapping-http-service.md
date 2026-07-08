---
spec_id: "onec-marketplace-mapping-http-service"
title: "1C marketplace mapping read-only HTTP service"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
source_of_truth: true
related_code: [src/wb_unit_economics/mapping.py, src/wb_unit_economics/contracts.py]
related_tests: [tests/test_mapping.py]
contracts: [sku_mapping]
depends_on: [docs/specs/wb-unit-economics-excel-mvp-implementation.md]
supersedes: []
rollout_required: true
updated_at: "2026-07-07"
---

# Goal

Добавить маленький read-only HTTP-сервис в `1С:УНФ` с установленным расширением
`ИС_Маркетплейс`, чтобы получать подтвержденное сопоставление товаров WB/Ozon и 1С
из регистров расширения без ручной TXT-выгрузки.

Сервис является источником raw snapshot для существующего контракта
`sku_mapping`. Ручные файлы `data/onec_marketplace_mapping/*.txt` остаются
fallback на случай, если публикация HTTP-сервиса временно недоступна.

Для клиентских внедрений предпочтительная упаковка этого HTTP-контракта -
отдельное расширение `.cfe`, описанное в
`docs/specs/onec-marketplace-mapping-client-extension.md`.

# Scope

Входит:

- HTTP-сервис 1С только с методами `GET`;
- endpoint проверки доступности `GET /hs/wb-unit-economics/v1/health`;
- endpoint сопоставления `GET /hs/wb-unit-economics/v1/mapping`;
- endpoint Ozon-сопоставления `GET /hs/wb-unit-economics/v1/mapping?marketplace=ozon`;
- чтение только из объектов расширения маркетплейса:
  `InformationRegister.ИС_WB_СоответствиеРазмеров`,
  `Catalog.ИС_WB_РазмерыНоменклатур`,
  `Catalog.ИС_WB_Номенклатура`,
  `InformationRegister.ИС_WB_ШтрихкодыРазмеров`,
  `InformationRegister.ИС_Ozon_СоответствиеХарактеристик`,
  `Catalog.ИС_Ozon_Номенклатура`;
- возврат JSON без токенов WB/Ozon, настроек кабинетов, паролей,
  raw payload WB/Ozon и
  служебных настроек обмена;
- нормализация ответа в существующий `sku_mapping` с `match_method =
  onec_marketplace_http`.

Не входит:

- запись в 1С, проведение документов, изменение справочников или регистров;
- чтение токенов WB, настроек профилей маркетплейса и секретов расширения;
- публикация всего OData-интерфейса расширения;
- расчет себестоимости;
- автоматическое создание или исправление маппинга;
- хранение ответа сервиса в Git или Markdown.

# External Documentation Check

Перед реализацией проверена официальная документация 1С:

- `https://v8.1c.ru/platforma/http-servisy/`;
- `https://v8.1c.ru/platforma/json/`;
- `https://v8.1c.ru/platforma/rest-interfeys/`.

Документация подтверждает, что HTTP-сервис прикладного решения сам формирует
ответ, может возвращать JSON и публикуется с обычной аутентификацией 1С.
Стандартный REST/OData интерфейс 1С поддерживает операции чтения и изменения
данных, поэтому для этого контура предпочтителен узкий кастомный HTTP-сервис.

# User Roles And Business Decisions

Роли:

- администратор 1С публикует HTTP-сервис и создает отдельного пользователя
  только на чтение;
- инженер проекта настраивает URL и учетные данные только в локальном runtime;
- консультант проверяет строки со статусами `missing` и `ambiguous`;
- клиент подтверждает, что форма сопоставления в расширении является
  актуальным источником связи WB/Ozon и 1С.

Бизнес-решение: если строка есть в регистре соответствия WB или Ozon, она имеет
приоритет над автоматическим сопоставлением по артикулу. Если из расширения
возвращаются разные номенклатуры 1С для одного товара маркетплейса, такая
связка получает статус `ambiguous`, а не выбирается автоматически.

# Read And Write Boundaries

Разрешено:

- читать активные записи регистра `ИС_WB_СоответствиеРазмеров`;
- читать связанные размеры WB из `ИС_WB_РазмерыНоменклатур`;
- читать связанные карточки WB из `ИС_WB_Номенклатура`;
- читать штрихкоды размеров из `ИС_WB_ШтрихкодыРазмеров`;
- читать Ozon-связи из `ИС_Ozon_СоответствиеХарактеристик`;
- читать безопасные товарные поля Ozon из `ИС_Ozon_Номенклатура`:
  `Код`, `Наименование`, `offer_id`, `sku`, `sku_fbs`, `sku_fbo`, `Штрихкод`;
- читать стандартную номенклатуру 1С и характеристики только через ссылки,
  уже сохраненные в регистре соответствия.

Запрещено:

- использовать методы `POST`, `PUT`, `PATCH`, `DELETE`;
- читать регистры, справочники или константы с токенами WB/Ozon;
- возвращать настройки профилей маркетплейса, ключи API, пароли или служебные
  параметры обмена;
- писать raw JSON в репозиторий.

# Data Contract

Endpoint `GET /hs/wb-unit-economics/v1/mapping` возвращает JSON object:

```json
{
  "schema_version": "1",
  "source": "1c_marketplace_http",
  "generated_at": "2026-07-04T12:00:00+03:00",
  "timezone": "Europe/Moscow",
  "row_count": 1,
  "truncated": false,
  "rows": [
    {
      "profile_key": "00000000-0000-0000-0000-000000000000",
      "nm_id": 123456789,
      "vendor_code": "WB-ART-1",
      "tech_size": "42",
      "wb_size": "42",
      "barcode": "4600000000000",
      "onec_item_id": "00000000-0000-0000-0000-000000000001",
      "onec_code": "000123",
      "onec_article": "ART-1",
      "onec_name": "Товар 1С",
      "onec_characteristic_id": "00000000-0000-0000-0000-000000000002",
      "onec_characteristic": "42",
      "status": "matched"
    }
  ]
}
```

Endpoint `GET /hs/wb-unit-economics/v1/mapping?marketplace=ozon` возвращает тот
же envelope и строки Ozon:

```json
{
  "schema_version": "1",
  "source": "1c_marketplace_http",
  "marketplace": "ozon",
  "generated_at": "2026-07-07T12:00:00+03:00",
  "timezone": "Europe/Moscow",
  "row_count": 1,
  "truncated": false,
  "rows": [
    {
      "marketplace": "ozon",
      "profile_key": "00000000-0000-0000-0000-000000000000",
      "ozon_item_id": "00000000-0000-0000-0000-000000000010",
      "product_id": "123456789",
      "offer_id": "OZ-ART-1",
      "sku": "987654321",
      "sku_fbs": "",
      "sku_fbo": "",
      "barcode": "4600000000000",
      "ozon_name": "Товар Ozon",
      "onec_item_id": "00000000-0000-0000-0000-000000000001",
      "onec_code": "000123",
      "onec_article": "ART-1",
      "onec_name": "Товар 1С",
      "onec_characteristic_id": "00000000-0000-0000-0000-000000000002",
      "onec_characteristic": "42",
      "package": "шт",
      "status": "matched"
    }
  ]
}
```

Поля:

- `profile_key`: технический идентификатор профиля маркетплейса в расширении.
  Название кабинета и организация 1С сопоставляются на стороне проекта через
  safe config.
- `nm_id`: код карточки из `Catalog.ИС_WB_Номенклатура.Код`.
- `vendor_code`: артикул продавца из `Catalog.ИС_WB_Номенклатура.vendorCode`.
- `tech_size`, `wb_size`: размерные поля из `Catalog.ИС_WB_РазмерыНоменклатур`.
- `barcode`: штрихкод из `InformationRegister.ИС_WB_ШтрихкодыРазмеров`.
- `onec_item_id`, `onec_code`, `onec_article`, `onec_name`: безопасные поля
  стандартной номенклатуры 1С.
- `onec_characteristic_id`, `onec_characteristic`: характеристика 1С, если
  используется.
- `status`: `matched`, `missing`, `ambiguous` или `excluded`.
- Ozon-поля `offer_id`, `product_id`, `sku`, `sku_fbs`, `sku_fbo`, `barcode`,
  `ozon_name` используются только для сопоставления и диагностики. Они не
  являются выручкой, расходами или себестоимостью.

# Normalization To `sku_mapping`

Нормализация ответа:

- `client_id`: tenant проекта;
- `seller_account_id`: берется из non-secret сопоставления `profile_key` к
  кабинету маркетплейса;
- `organization_id`: берется из non-secret сопоставления кабинета маркетплейса к
  организации 1С;
- `nm_id`, `vendor_code`, `barcode`: из HTTP-ответа;
- `onec_item_id`: из `onec_item_id`;
- `onec_article`: из `onec_article`;
- `onec_characteristic`: из `onec_characteristic`;
- `match_method`: `onec_marketplace_http`;
- для Ozon diagnostic mart match method нормализуется как
  `onec_marketplace_ozon_offer`, `onec_marketplace_ozon_product_id`,
  `onec_marketplace_ozon_sku`, `onec_marketplace_ozon_barcode` или
  `onec_marketplace_ozon_name`;
- `confidence`: `1` для `matched`, `0.5` для `ambiguous`, `0` для `missing`;
- `updated_by`: `1c_marketplace_http`;
- `updated_at`: время получения snapshot.

Если для одного `seller_account_id + nm_id + vendor_code` пришло несколько
разных `onec_item_id`, итоговая связь получает статус `ambiguous`.

# Security, Tenant Isolation, Audit, Retention

- Учетная запись 1С для HTTP-сервиса должна иметь только чтение нужных объектов.
- Публикацию желательно ограничить по IP сервера проекта.
- URL и пароль хранятся только в локальном runtime, не в Git и не в Markdown.
- Ответ сервиса сохраняется только в `data/` как raw snapshot с manifest и hash.
- В логах допустимы только endpoint, HTTP status, row count, duration и
  snapshot id; тело ответа и секреты не логируются.
- Raw snapshots удаляются по общей retention-политике `source_refresh`; перед
  удалением нужен dry-run.

# Errors And Edge Cases

- `401` или `403`: доступ не настроен или права пользователя 1С недостаточны.
- `404`: HTTP-сервис не опубликован или URL отличается.
- `405`: вызван метод не `GET`; запись не выполняется.
- `500`: ошибка запроса 1С; ответ должен содержать короткий безопасный текст,
  без внутренних токенов и raw data.
- Пустой ответ считается `needs_review`, а не успешным маппингом.
- Незаполненная номенклатура 1С в регистре возвращается как `missing`.
- Дубликаты штрихкодов не склеиваются молча; нормализатор должен показать
  `ambiguous` или отдельный диагностический блок.

# Acceptance Criteria

- В 1С создан HTTP-сервис с двумя `GET` endpoint.
- Пользователь сервиса не может записывать документы, справочники или регистры.
- `GET /health` возвращает `200` и JSON со статусом `ok`.
- `GET /mapping` и `GET /mapping?marketplace=ozon` возвращают только поля из
  этого spec.
- Ответ не содержит WB/Ozon API token, password, secret, client raw payload или
  настройки профиля маркетплейса.
- Проект может сохранить ответ как локальный ignored snapshot в `data/`.
- Существующая TXT-выгрузка остается fallback и не удаляется.

# Test Plan

Проверки на стороне 1С:

- вызвать `GET /health` под отдельным read-only пользователем;
- вызвать `GET /mapping?limit=10` и проверить структуру JSON;
- вызвать `GET /mapping?marketplace=ozon&limit=10` и проверить структуру JSON;
- под тем же пользователем вручную убедиться, что запись в объекты 1С
  запрещена;
- проверить, что в ответе нет секретов и настроек профилей.

Проверки на стороне проекта:

- сохранить raw JSON в `data/`;
- проверить manifest: URL без пароля, status code, row count, hash;
- нормализовать sample в `sku_mapping`;
- сравнить количество `matched`, `missing`, `ambiguous`;
- собрать Excel MVP и убедиться, что строки без маппинга остаются видимыми как
  проблемы качества данных.

# Rollout And Rollback

Rollout:

1. Добавить HTTP-сервис через отдельное клиентское расширение 1С или вручную в
   тестовой доработке.
2. Опубликовать сервис на тестовой базе.
3. Проверить `health` и маленький `mapping` sample.
4. Ограничить доступ по IP и read-only пользователю.
5. Подключить URL в локальном runtime проекта.
6. Снять первый snapshot и сверить с ручной выгрузкой формы сопоставления.

Rollback:

- снять публикацию HTTP-сервиса или заблокировать пользователя;
- вернуть проект на ручные файлы `data/onec_marketplace_mapping/*.txt`;
- не удалять уже сохраненные локальные snapshots до окончания сверки.

# Changelog

- 2026-07-07 — added Ozon mapping endpoint over
  `ИС_Ozon_СоответствиеХарактеристик` and `ИС_Ozon_Номенклатура` without
  reading Ozon API tokens or profile settings.
- 2026-07-04 — accepted V1 spec for narrow read-only 1C HTTP service over
  marketplace mapping registers.
