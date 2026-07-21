---
title: "Probe доступности источников логистики (F-0 / R-0 / C-0)"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "agent", "operations"]
status: active
source_of_truth: false
source_spec: "docs/specs/wb-logistics-cost-analysis-implementation.md"
updated_at: "2026-07-21"
---

# Назначение

Операционный чеклист для проверки доступности внешних WB-источников перед
реализацией второй/третьей очереди логистики. Он превращает разделы probe трёх
черновиков в один воспроизводимый прогон, который выполняет держатель
авторизованных read-only токенов.

Draft-спеки, для которых нужен этот probe:

- вторая очередь (факторы) — `docs/specs/wb-logistics-cost-factors-implementation.md`;
- причины возвратов — `docs/specs/wb-logistics-return-reasons-implementation.md`;
- калькуляторы (третья очередь) — `docs/specs/wb-logistics-calculators-implementation.md`.

Канонический источник истины scope — accepted
`docs/specs/wb-logistics-cost-analysis-implementation.md`; при расхождении
действует он. Этот runbook не заменяет спеки и ничего не согласовывает сам.

**Статус на 2026-07-21:** базовый живой probe F-1…F-3 выполнен; для F-4
официальный schema contract подтверждён, но live-вызовы двух measurement
endpoint ещё не выполнялись. Ниже — безопасный gate перед F-4 product-кодом.

# Безопасность прогона

- Только read-only методы. Никаких write-вызовов (в частности, `POST
  returns-api /api/v1/claim`, обновление карточек товара) — запрещено.
- Raw payload, клиентские объёмы и персональные данные покупателя (`user_comment`,
  фото) НЕ копируются в Git, Markdown, вывод или тикеты. В отчёт probe попадают
  только обезличенные агрегаты (доли покрытия, доли `unmatched`, наличие полей).
- Токены — минимально необходимых категорий (least privilege), не логировать.
- Отчёт probe сохранять локально (`reports/` — вне Git) как обезличенную матрицу
  доступности.

# Предусловия: токены и лимиты

| Источник | Категория токена | Rate limit | Read-only |
|---|---|---|---|
| Content `cards/list` (габариты) | Контент | см. офиц. лимит | да |
| Statistics `supplier/sales` (склад/направление) | Статистика | см. офиц. лимит | да |
| Tariffs `tariffs/box|pallet` | Тарифы | 60 запросов/мин | да |
| Analytics `measurement-penalties` (замеры/удержания) | Аналитика | 1 запрос/мин | да |
| Analytics `warehouse-measurements` (складские замеры) | Аналитика | 1 запрос/мин | да |
| Analytics `goods-return` (reason) | Аналитика | 1 запрос/мин | да |
| Returns `claims` (user_comment) | Возвраты покупателями | 20 запросов/мин | да |

Планировать раздельный бюджет запросов и backoff на HTTP 429. Все Analytics
методы с лимитом 1/мин вызываются последовательно. Общий Finance `penalty` не
используется как источник F-4: официальный Finance contract не содержит
замеренных габаритов и не доказывает причину удержания.

# Прогон probe

Для каждого источника зафиксировать один из трёх статусов: `подтверждён`,
`частично`, `недоступен`.

## F-0. Факторы (вторая очередь)

1. **Габариты (Content):** на срезе отчёта — доля товаров с непустым
   `dimensions` и распределение `isValid`. Записать: % заполненных габаритов,
   % `isValid=false`.
2. **Склад/направление (Statistics):** покрытие `warehouseName`,
   `countryName/oblastOkrugName/regionName` за период отчёта. Записать: % строк с
   складом и с направлением; хватает ли глубины 90 дней.
3. **Тарифы (Tariffs):** доступен ли архив box/pallet за нужные исторические
   недели; какая самая ранняя дата отдаётся; совпадает ли `warehouseName` тарифа
   со складом продаж. Проверить наличие/имя параметра `date` и полей
   `dtNextBox`/`dtTillMax`.
4. **Замеры/удержания (Analytics Reports):** отдельно проверить read-only
   `GET /api/analytics/v1/measurement-penalties` и
   `GET /api/analytics/v1/warehouse-measurements` для каждого разрешённого
   кабинета. Первый вызов — `limit=1`, без сохранения body. Зафиксировать только
   safe status и наличие ожидаемой envelope/schema; затем отдельным контролем
   проверить полную offset-pagination и provider `total` без вывода значений.

## R-0. Причины возвратов

5. **goods-return:** доступ токена «Аналитика»; для 31-дневных окон периода —
   доля возвратов с непустым `reason`, распределение `status`/`returnType`.
6. **claims:** доступ токена «Возвраты покупателями»; активные (14 дней) и архив
   (`is_archive=true`) — глубина архива, доля непустых `user_comment`, наличие
   `srid`.
7. **Join по `srid`:** доля финансовых возвратов среза, сопоставимых с
   goods-return и claims; доля `unmatched` в обе стороны. НЕ смешивать
   `goods-return.reason` и `claims.user_comment`.

## C-0. Калькуляторы (третья очередь)

8. Подтвердить, что тарифы (шаг 3) достаточны для сценарного расчёта за период.
9. Подтвердить, что габариты/вес (шаг 1) годятся как предзаполнение.
10. Сверить, что маржинальный waterfall совпадает с методикой отчёта на
    контрольном товаре (без внешних вызовов — это внутренняя проверка).

# Результат и решение

Оформить обезличенную матрицу доступности (аналог матрицы этапа 0 первой
очереди):

| Источник | Статус | Покрытие | Вывод для scope |
|---|---|---|---|

- `подтверждён` → подпакет включается в реализацию;
- `частично` → включается с явным `data_unavailable`/диапазоном там, где нет
  покрытия;
- `недоступен` → подпакет переносится; факт не заполняется нулём и не
  подменяется гипотезой.

Матрица определяет порядок подпакетов F-1…F-4, R-1…R-3 и C-1…C-3 в
соответствующих черновиках. Источник, делающий требование невыполнимым,
возвращается на согласование спека, а не обходится молча.

# Результаты живого probe (2026-07-19)

Первый живой read-only прогон выполнен штатным скриптом
`scripts/probe_wb_logistics_factors.py` (ключ WB берётся из tenant_integrations
тем же путём, что и source refresh; в вывод идут только агрегаты). Тест-контур
рабочего ключа не имеет (обе WB-интеграции `disabled`, secret не восстановим),
поэтому прогон выполнен с прод-env read-only; прод-система не менялась.

Перезапуск (оператор, на сервере):

```bash
( set -a; . /etc/shumeiko-web-prod.env; set +a; \
  PYTHONPATH=/opt/shumeyko-partners-wb-unit-economics/src \
  /opt/shumeyko-partners-wb-unit-economics/.venv/bin/python \
  scripts/probe_wb_logistics_factors.py )
```

На разрешённых WB-интеграциях подтверждены read-only тарифы и goods-return;
Statistics/claims доступны не для каждого token scope. В evidence сохранены
только безопасные статусы доступности и имена полей — без числа кабинетов,
provider labels, клиентских объёмов или идентификаторов. Подтверждённые schema:
тарифы — `boxDeliveryCoefExpr`/`palletDeliveryExpr`, `warehouseName`, периоды
`dtNextBox`/`dtNextPallet`/`dtTillMax`; goods-return — `reason`, `srid`, `nmId`,
`status`, `returnType`; Statistics — `warehouseName`, `countryName`,
`oblastOkrugName`, `regionName`, `srid`. Габариты уже реализованы (F-1), данные
в сохранённых карточках.

Вывод: F-1…F-3 технически доступны с явным per-cabinet partial scope. Отсутствие
scope не обходится другим токеном и не скрывается общим успешным статусом.

# F-4 live source gate

До изменения collector/mart/API выполнить минимальный read-only probe на test
или в отдельном процессе с действующим service environment. Скрипт не должен
печатать integration/provider names, число кабинетов, `total`, raw rows или
значения полей.

Текущий `scripts/probe_wb_logistics_factors.py` F-4 endpoints ещё не вызывает и
для этого gate не подходит. В отдельной implementation-ветке сначала добавить
безопасный F-4 mode и unit-тест, запрещающий вывод provider labels/counts/raw
values; до этого environment status F-4 остаётся `not_probed`.

Для каждого разрешённого кабинета и каждого F-4 endpoint зафиксировать только:

- `confirmed_empty` — HTTP 200, ожидаемая envelope/schema, `reports` пуст;
- `confirmed_nonempty` — HTTP 200, ожидаемая envelope/schema, есть хотя бы одна
  строка; значения и count не выводятся;
- `access_denied` — HTTP 401/403;
- `unavailable` — timeout/429/5xx после ограниченного retry;
- `schema_mismatch` — HTTP 200, но контракт envelope/ключей не совпал.

Probe использует `limit=1`, `offset=0`, обязательный `dateTo` и безопасное
покрывающее окно. После первого status-probe отдельный локальный прогон может
проверить всю pagination: следующий offset увеличивается на число полученных
строк до сверки с provider `total`. В Git/Markdown попадает только булев
результат reconciliation, не `total`, count, период с клиентской активностью,
размеры, суммы, `dimId`, `nmId` или `photoUrls`.

`confirmed_empty` и `confirmed_nonempty` подтверждают endpoint. `access_denied`
или `unavailable` дают per-cabinet `partial/data_unavailable`, но не разрешают
подменить источник Finance. `schema_mismatch` блокирует начало реализации и
возвращает контракт на review. Наличие ненулевого удержания не является
условием source gate.

Implementation gate открывается, только если каждый из двух endpoint имеет
хотя бы один `confirmed_empty|confirmed_nonempty` на разрешённом кабинете и нет
`schema_mismatch`. Остальные кабинеты сохраняют собственный partial status;
общий успех не скрывает их недоступность.

# После probe

1. Записать в operational evidence только дату/revision, safe endpoint statuses
   и булев результат schema/pagination reconciliation; обновить раздел
   «Открытые вопросы» factor-spec.
2. При отсутствии `schema_mismatch` начинать реализацию принятого F-4 контракта
   отдельной веткой за выключенным флагом. При mismatch сначала обновить spec.
3. Не публиковать raw и не менять production без отдельного разрешения.
